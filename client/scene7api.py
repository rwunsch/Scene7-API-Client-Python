import json
import logging
import argparse
import zeep
from zeep import Client, Settings
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from requests.auth import HTTPBasicAuth
import requests

def load_config(file_path):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except Exception as e:
        print(f"Error loading config file {file_path}: {e}")
        raise

def setup_logging(debug):
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger('zeep').setLevel(logging.DEBUG)
        logging.getLogger('zeep.transport').setLevel(logging.DEBUG)
        logging.getLogger('zeep.client').setLevel(logging.DEBUG)
        logging.getLogger('zeep.wsdl').setLevel(logging.DEBUG)

def create_client(auth_config):
    try:
        session = requests.Session()
        session.auth = HTTPBasicAuth(auth_config['username'], auth_config['password'])
        transport = Transport(session=session)
        settings = Settings(strict=False, xml_huge_tree=True)
        history = HistoryPlugin()
        client = Client(wsdl=auth_config['wsdl_url'], transport=transport, settings=settings, plugins=[history])
        client.service._binding_options['address'] = auth_config['service_url']
        return client, history
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        raise
    except Exception as e:
        print(f"Error creating SOAP client: {e}")
        raise

def list_available_methods(client):
    print("Available Services:")
    for service in client.wsdl.services.values():
        print(f"Service: {service.name}")
        for port in service.ports.values():
            print(f"  Port: {port.name}")
            operations = sorted(port.binding._operations.values(), key=lambda op: op.name)
            for operation in operations:
                print(f"    Operation: {operation.name}")

def execute_command(client, command):
    try:
        command_name = command['name']
        params = command['params']
        service = client.service
        method = getattr(service, command_name, None)
        if method:
            response = method(**params)
            return response
        else:
            print(f"Command {command_name} not found in the service.")
            list_available_methods(client)
            raise ValueError(f"Command {command_name} not found in the service.")
    except Exception as e:
        print(f"Error executing command {command['name']}: {e}")
        raise

def print_history(history):
    for item in history.items:
        print(f"Request:\n{item.request}\n")
        print(f"Response:\n{item.response}\n")

def parse_command_line_args():
    parser = argparse.ArgumentParser(
        description="Scene7 API Client",
        epilog=(
            "Example usage:\n"
            "  python3 scene7api.py --method getCompanyInfo --params companyName=Planetary anotherParam=value\n\n"
            "You can also use the command_config.json file to specify the commands.\n"
            "Commands provided as script parameters take precedence over the configuration file."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--method", type=str, help="API method to call")
    parser.add_argument("--params", type=str, nargs='*', help="Key-value pairs of parameters for the API method (e.g., key1=value1 key2=value2)")
    parser.add_argument("--debug", action='store_true', help="Enable debug logging")
    args = parser.parse_args()

    command = {}
    if args.method:
        command['name'] = args.method
        command['params'] = {}
        if args.params:
            for param in args.params:
                key, value = param.split('=')
                command['params'][key] = value
    return command, args.debug

def main():
    try:
        auth_config = load_config('auth_config.json')
        command_config = load_config('command_config.json')

        # Parse command line arguments
        command_line_command, debug_flag = parse_command_line_args()

        # Determine which command to use (command line takes preference)
        if command_line_command and 'name' in command_line_command:
            commands = [command_line_command]
        else:
            commands = command_config['commands']

        # Setup logging based on debug parameter (command line takes preference)
        debug = debug_flag if debug_flag is not None else auth_config.get('debug', False)
        setup_logging(debug)

        client, history = create_client(auth_config)

        for command in commands:
            try:
                response = execute_command(client, command)
                print(f"Response for {command['name']}: {response}")
            except Exception as e:
                print(f"Error executing {command['name']}: {e}")

        # Print request and response history if debug is enabled
        if debug:
            print_history(history)

    except Exception as e:
        print(f"An error occurred in the main function: {e}")

if __name__ == "__main__":
    main()