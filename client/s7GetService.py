from zeep import Client

wsdl_url = "https://s7sps3apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl"
client = Client(wsdl=wsdl_url)

print("Available Services:")
for service in client.wsdl.services.values():
    print(f"Service: {service.name}")
    for port in service.ports.values():
        print(f"  Port: {port.name}")
        operations = sorted(port.binding._operations.values(), key=lambda op: op.name)
        for operation in operations:
            print(f"    Operation: {operation.name}")
