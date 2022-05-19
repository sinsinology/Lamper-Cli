from __future__ import print_function
from datetime import datetime
import argparse
import codecs
import boto3
from boto3.session import Session
from botocore.exceptions import ClientError
from terminaltables import AsciiTable
from tqdm import tqdm
import os
import uuid
import requests
import datetime as pythontime
import zipfile
import coloredlogs, logging
import colorama

logger = logging.getLogger(__name__)
coloredlogs.install(level='CRITICAL')
coloredlogs.install(level='CRITICAL', logger=logger)


OUTPUT_FOLDER = "lamper-output/"
exportPath = OUTPUT_FOLDER  + pythontime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + "/functions/"


DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'
BYTE_TO_MB = 1024.0 * 1024.0

ALL_TABLE_HEADERS = [
    'Region',
    'Function',
    'Memory (MB)',
    'Code Size (MB)',
    'Timeout (seconds)',
    'Runtime',
    'Last Modified',
    'Last Invocation',
    'Description',
]

SORT_KEYS = ['region', 'last-modified', 'last-invocation', 'runtime']


def banner():

    print( colorama.Fore.LIGHTYELLOW_EX + """
     ____________________________
< Lamper (AWS Lambda Mapper) By @MDSecLabs>
< Version: 0.2.2 >
 ----------------------------
\
 \
         ,=;%$%%$X%%%%;/%%%%;=,
     ,/$$+:-                -:+$$/,
   :X$=                          =$X:
 ;M%.                              .%M;
+#/                                  /#+
##                                    M#
H#,                     =;+/;,       ,#X
.HM-       :@X+%H:   .%M%- .M#.     -M@.
  /#%.     @#-  ,H@--MH, .;@$-    .%#+
   .$M;    .+@X;, MM#@:/$X;.     ;M$,
     =@H,     ,:+%H#M%;-       ,H@=
      .$#;        -#H         =#$
        %#;        #M        ;#%
         H#-       ##       -#H
         ;#+       ##       +#;
          ;H+;;;;;;HH;;;;;;+H/
           =H#@HHHHHHHHHH@#H=
           =@#H%%%%%%%$HH@#@=
           =@#X%%%%%%%$M###@=
               =+%XHHX%+=

               """ )



def list_available_lambda_regions():
    """
    Enumerates list of all Lambda regions
    :return: list of regions
    """
    logger.info("Authenticating to AWS")

    session = Session()
    return session.get_available_regions('lambda')


def init_boto_client(client_name, region, args):
    """
    Initiates boto's client object
    :param client_name: client name
    :param region: region name
    :param args: arguments
    :return: Client
    """
    if args.token_key_id and args.token_secret:
        boto_client = boto3.client(
            client_name,
            aws_access_key_id=args.token_key_id,
            aws_secret_access_key=args.token_secret,
            region_name=region
        )
    elif args.profile:
        session = boto3.session.Session(profile_name=args.profile)
        boto_client = session.client(client_name, region_name=region)
    else:
        boto_client = boto3.client(client_name, region_name=region)

    return boto_client


def get_days_ago(datetime_obj):
    """
    Converts a datetime object to "time ago" string
    :param datetime_obj: Datetime
    :return: "time ago" string
    """
    days_ago = (datetime.now() - datetime_obj).days
    datetime_str = 'Today'
    if days_ago == 1:
        datetime_str = 'Yesterday'
    elif days_ago > 1:
        datetime_str = '{0} days ago'.format(days_ago)

    return datetime_str


def get_last_invocation(region, args, function_name):
    """
    Return last invocation timestamp (epoch) or -1 if not found.
    -1 can be returned if no log group exists for Lambda,
    or if there are no streams in the log.
    :param region: function region
    :param args: arguments
    :param function_name: function name
    :return: last invocation or -1
    """
    logs_client = init_boto_client('logs', region, args)
    last_invocation = -1

    try:
        logs = logs_client.describe_log_streams(
            logGroupName='/aws/lambda/{0}'.format(function_name),
            orderBy='LastEventTime',
            descending=True
        )
    except ClientError as _:
        return last_invocation

    log_streams_timestamp = [
        log.get('lastEventTimestamp', 0) for log in logs['logStreams']
    ]

    if log_streams_timestamp:
        last_invocation = max(log_streams_timestamp)

    return last_invocation


def create_tables(lambdas_data, args):
    """
    Create the output tables
    :param lambdas_data: a list of the Lambda functions and their data
    :param args: argparse arguments
    :return: textual table-format information about the Lambdas





    """
    all_table_data = [ALL_TABLE_HEADERS]
    report_rows = []
    viz_function_nodes = []
    viz_relations_nodes = []
    runtimes = []
    for lambda_data in lambdas_data:
        function_data = lambda_data['function-data']
        last_invocation = 'N/A (no invocations?)'
        if lambda_data['last-invocation'] != -1:
            last_invocation = get_days_ago(
                datetime.fromtimestamp(lambda_data['last-invocation'] / 1000)
            )
        all_table_data.append([
            lambda_data['region'],
            str(function_data['FunctionName']),
            str(function_data['MemorySize']),
            '%.2f' % (function_data['CodeSize'] / BYTE_TO_MB),
            str(function_data['Timeout']),
            str(function_data['Runtime']) if 'Runtime' in function_data else '',
            get_days_ago(lambda_data['last-modified']),
            last_invocation,
            '"' + function_data['Description'] + '"'
        ])

        if(lambda_data['sourcecode'] == 'N/A'):
            report_rows.append(f"""
                                <tr>
                                    <td>{str(function_data['FunctionName'])}</td>
                                    <td>N/A</td>
                                    <td>{lambda_data['region']}</td>
                                    <td>{function_data['Description']}</td>
                                    <td>{get_days_ago(lambda_data['last-modified'])}</td>
                                    <td>{last_invocation}</td>
                                    <td>
                                    N/A
                                    </td>
                                </tr>
            """)
        else:
            report_rows.append(f"""
                                <tr>
                                    <td>{str(function_data['FunctionName'])}</td>
                                    <td>{str(function_data['Runtime'])}</td>
                                    <td>{lambda_data['region']}</td>
                                    <td>{function_data['Description']}</td>
                                    <td>{get_days_ago(lambda_data['last-modified'])}</td>
                                    <td>{last_invocation}</td>
                                    <td>
                                <div class="btn-group d-flex" role="group" aria-label="...">


                                    <!--  <a href='{lambda_data['scan_secrets']}' target="_blank" data-toggle="tooltip" data-placement="top" title="Secrets" type="button" class="btn btn-warning w-100"><i class="fa fa-key"></i></a> -->
                                    <!-- <a href='{lambda_data['scan_vulns']}' target="_blank" data-toggle="tooltip" data-placement="top" title="Vulnerability Scan" type="button" class="btn btn-danger w-100"><i class="fa fa-bug"></i></a> -->
                                    <a href='{"functions" + lambda_data['sourcecode'].replace("lamper-output", '').split("functions")[1]}' target="_blank" data-toggle="tooltip" data-placement="top" title="Source Code" type="button" class="btn btn-primary w-100"><i class="fa fa-download"></i></a>
                                    </td>
                                </tr>
            """)

        viz_function_nodes.append("""
        { id: "FUNCTION_NAME", label: "FUNCTION_NAME", shape: "dot", size:10 },
        """.replace("FUNCTION_NAME", str(function_data['FunctionName'])))

        viz_relations_nodes.append("""
        { from: "FUNCTION_NAME", to: "REGION_NAME" },
        """.replace("FUNCTION_NAME", str(function_data['FunctionName'])).replace("REGION_NAME", lambda_data['region']))

        runtimes.append('N/A')



    if args.should_print_all:
        min_table_data = all_table_data
    else:
        # Get only the region, function, last modified and last invocation
        min_table_data = [
            [
                lambda_data[0], lambda_data[1], lambda_data[5], lambda_data[-2], lambda_data[-1]
            ]
            for lambda_data in all_table_data
        ]


    viz_regions_nodes = []

    for vizRegion in list_available_lambda_regions():
        viz_regions_nodes.append("""
                { id: "REGION", label: "REGION" , shape: "triangle", color: "#FFA807"},

        """.replace("REGION", vizRegion))


    report_template = requests.get("https://cdn.rawgit.com/sinsinology/Lamper-Cli/main/assets/plugins/report.html")
    filedata = report_template.text

    # Replace the target string
    filedata = filedata.replace('REPLACE_REPORT_DATA', ''.join(report_rows))
    filedata = filedata.replace('REPLACE_VIZ_REGIONS_NODES', ''.join(viz_regions_nodes))
    filedata = filedata.replace('REPLACE_VIZ_FUNCTIONS_NODES', ''.join(viz_function_nodes))
    filedata = filedata.replace('REPLACE_VIZ_REPLATION_NODES', ''.join(viz_relations_nodes))

    filedata = filedata.replace('REPLACE_DATE', pythontime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    labels = list(set(runtimes)) # ['java', 'python']
    labels_string = "['" + "','".join(labels) + "']"

    filedata = filedata.replace('REPLACE_LABELS', labels_string)

    labels_count = []

    for label in labels:
        labels_count.append(runtimes.count(label))

    labels_count = [str(int) for int in labels_count]

    labels_count_string = "[" + ",".join(labels_count) + "]"
    filedata = filedata.replace('REPLACE_COUNTS', labels_count_string)


    # Write the file out again
    with open(exportPath.replace('functions/', '') + '/Report.html', 'w') as file:
      file.write(filedata)

    print("\r\n")
    print(colorama.Fore.LIGHTGREEN_EX)
    print("[Success] " + exportPath.replace('functions/', '') + 'Report.html' +" is ready")

    return min_table_data, all_table_data


def scan_secrets(lambda_package_zip):
    return lambda_package_zip + "_whisper_result"

def scan_vulns(lambda_package_zip):
    return lambda_package_zip + "_vuln_scan"




def print_lambda_list(args):
    logger.info("Launching Lamper")



    if(not(os.path.exists(OUTPUT_FOLDER))):
        os.mkdir(OUTPUT_FOLDER)




    os.makedirs(exportPath)




    """
    Main function
    :return: None
    """
    logger.info("this is an informational message")

    regions = list_available_lambda_regions()
    lambdas_data = []
    print(colorama.Fore.LIGHTYELLOW_EX)
    for region in tqdm(regions):
        lambda_client = init_boto_client('lambda', region, args)
        next_marker = None
        try:
            response = lambda_client.list_functions()
        except Exception as e:
            print(colorama.Fore.LIGHTCYAN_EX)
            print("[EXIT] Received Error (make sure you've added AWS keys to your env variable):")
            print(e)
            exit()
        while next_marker != '':
            next_marker = ''
            functions = response['Functions']
            if not functions:
                continue

            for function_data in functions:
                # Extract last modified time
                last_modified = datetime.strptime(
                    function_data['LastModified'].split('.')[0],
                    DATETIME_FORMAT
                )


                func_details  = lambda_client.get_function(FunctionName=function_data['FunctionName'])
                sourcecode_zip = exportPath + function_data['FunctionName'] + "-" + str(uuid.uuid4()) + '.zip'
                try:
                    url = func_details['Code']['Location']
                    r = requests.get(url)
                    with open(sourcecode_zip, "wb") as code:
                        code.write(r.content)
                    scan_vulns_result = scan_vulns(sourcecode_zip)
                    scan_secrets_result = scan_secrets(sourcecode_zip)
                except:
                    sourcecode_zip = "N/A"
                    scan_vulns_result = "N/A"
                    scan_secrets_result = "N/A"
		# Extract last invocation time from logs
                last_invocation = get_last_invocation(
                    region,
                    args,
                    function_data['FunctionName']
                )

                if last_invocation != -1:
                    inactive_days = (
                        datetime.now() -
                        datetime.fromtimestamp(last_invocation / 1000)
                    ).days
                    if args.inactive_days_filter > inactive_days:
                        continue

#                print(function_data)
                lambdas_data.append({
                    'sourcecode' : sourcecode_zip,
                    'scan_vulns' : scan_vulns_result,
                    'scan_secrets' : scan_secrets_result,
                    'region': region,
                    'function-data': function_data,
                    'last-modified': last_modified,
                    'last-invocation': last_invocation,
                    'runtime': function_data['Runtime'] if 'Runtime' in function_data else ''
                })

            # Verify if there is next marker
            if 'NextMarker' in response:
                next_marker = response['NextMarker']
                response = lambda_client.list_functions(Marker=next_marker)

    # Sort data by the given key (default: by region)
    lambdas_data.sort(key=lambda x: x[args.sort_by])

    min_table_data, all_table_data = create_tables(lambdas_data, args)
    print(colorama.Fore.LIGHTYELLOW_EX)

    if not args.csv:
        return

    with codecs.open(args.csv, 'w', encoding='utf-8') as output_file:
        for table_row in all_table_data:
            output_line = '{0}\n'.format(','.join(table_row))
            output_file.writelines(output_line)


def main():
    banner()
    parser = argparse.ArgumentParser(
        description=(
            'Enumerates Lambda functions from every region with '
            'interesting metadata.'
        )
    )

    parser.add_argument(
        '--all',
        dest='should_print_all',
        default=False,
        action='store_true',
        help=(
            'Print all the information to the screen '
            '(default: print summarized information).'
        )
    )
    parser.add_argument(
        '--csv',
        type=str,
        help='CSV filename to output full table data.',
        metavar='output_filename'
    )
    parser.add_argument(
        '--token-key-id',
        type=str,
        help=(
            'AWS access key id. Must provide AWS secret access key as well '
            '(default: from local configuration).'
        ),
        metavar='token-key-id'
    )
    parser.add_argument(
        '--token-secret',
        type=str,
        help=(
            'AWS secret access key. Must provide AWS access key id '
            'as well (default: from local configuration.'
        ),
        metavar='token-secret'
    )
    parser.add_argument(
        '--inactive-days-filter',
        type=int,
        help='Filter only Lambda functions with minimum days of inactivity.',
        default=0,
        metavar='minimum-inactive-days'
    )
    parser.add_argument(
        '--sort-by',
        type=str,
        help=(
            'Column name to sort by. Options: region, '
            'last-modified, last-invocation, '
            'runtime (default: region).'
        ),
        default='region',
        metavar='sort_by'
    )
    parser.add_argument(
        '--profile',
        type=str,
        help=(
            'AWS profile. Optional '
            '(default: "default" from local configuration).'
        ),
        metavar='profile'
    )

    arguments = parser.parse_args()
    if arguments.sort_by not in SORT_KEYS:
        print('ERROR: Illegal column name: {0}.'.format(arguments.sort_by))
        exit(1)

    print_lambda_list(arguments)


if __name__ == '__main__':
    main()
