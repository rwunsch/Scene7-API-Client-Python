# Scene7 API Client

This repository contains a Python script (`scene7api.py`) to interface with Adobe's [Scene7 IPS Web Service WSDL via SOAP](https://experienceleague.adobe.com/en/docs/dynamic-media-developer-resources/image-production-api/c-wsdl-versions). The script allows you to call various [API methods](https://experienceleague.adobe.com/en/docs/dynamic-media-developer-resources/image-production-api/operation-methods/operation-parameters/c-methods), either by specifying them in a configuration file (`command_config.json`) or by passing them as command-line parameters. Command-line parameters take precedence over the configuration file.

## Features

- Call [Adobe Scene7 IPS Web Service API methods](https://experienceleague.adobe.com/en/docs/dynamic-media-developer-resources/image-production-api/operation-methods/operation-parameters/c-methods).
- Support for both configuration file and command-line parameters.
- Debugging capabilities to log raw SOAP requests and responses.
- Detailed help function for command-line usage.

## Prerequisites

- Python 3.x
- `zeep` library for SOAP client
- `requests` library for HTTP requests

You can install the required libraries using pip:

```bash
pip install zeep requests
```

## Configuration

### auth_config.json

This file contains the authentication details and other configuration settings.

```json
{
    "username": "your_username",
    "password": "your_password",
    "wsdl_url": "https://s7sps3apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
    "service_url": "https://s7sps3apissl.scene7.com/scene7/services/IpsApiService",
    "debug": true
}
```

### command_config.json

This file contains the API commands you want to execute.

```json
{
    "commands": [
        {
            "name": "getCompanyInfo",
            "params": {
                "companyName": "Planetary"
            }
        }
    ]
}
```

## Usage

### Running the Script with Command-Line Parameters

You can run the script with multiple key-value pairs as parameters. For example:

```bash
python3 scene7api.py --method getCompanyInfo --params companyName=Planetary anotherParam=value --debug
```

### Running the Script without Command-Line Parameters

If you do not provide command-line parameters, the script will fall back to using the `command_config.json` file:

```bash
python3 scene7api.py
```

### Help Function

You can display the help message by running:

```bash
python3 scene7api.py --help
```

This will display a help message with descriptions of the available command-line arguments and an example of how to use the script.

```plaintext
usage: scene7api.py [--method METHOD] [--params PARAMS [PARAMS ...]] [--debug]

Scene7 API Client

optional arguments:
  --method METHOD     API method to call
  --params PARAMS [PARAMS ...]
                      Key-value pairs of parameters for the API method (e.g., key1=value1 key2=value2)
  --debug             Enable debug logging

Example usage:
  python3 scene7api.py --method getCompanyInfo --params companyName=Planetary anotherParam=value

You can also use the command_config.json file to specify the commands.
Commands provided as script parameters take precedence over the configuration file.
```

## Demo Video

A demo video demonstrating the usage of the script is available in the `demo` subfolder. You can watch the video by opening `demo/scene7api.mp4`.

## Script Details

### scene7api.py

This Python script interfaces with Adobe's Scene7 IPS Web Service WSDL via SOAP. It supports both configuration file and command-line parameters for specifying API method calls and parameters.

#### Key Functions

- **load_config**: Loads JSON configuration files.
- **setup_logging**: Sets up logging for debugging.
- **create_client**: Creates a SOAP client using the `zeep` library.
- **list_available_methods**: Lists available API methods.
- **execute_command**: Executes the specified API command.
- **print_history**: Prints the raw SOAP request and response history if debugging is enabled.
- **parse_command_line_args**: Parses command-line arguments.

## Example Configuration

### auth_config.json

```json
{
    "username": "your_username",
    "password": "your_password",
    "wsdl_url": "https://s7sps3apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
    "service_url": "https://s7sps3apissl.scene7.com/scene7/services/IpsApiService",
    "debug": true
}
```

### command_config.json

```json
{
    "commands": [
        {
            "name": "getCompanyInfo",
            "params": {
                "companyName": "Planetary"
            }
        }
    ]
}
```

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue if you have any suggestions or improvements.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.