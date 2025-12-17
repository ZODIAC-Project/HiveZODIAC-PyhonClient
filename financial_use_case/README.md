This Folder holds the files used in the financial use case example.

This use case consists of 5 main parts. Some are implemented at differend location. The location of the parts are mentioned in the description of each part.

1. The data generation (POS)
2. The broker (External)
3. The MCP Server (External)
4. The LLM (External)
5. The Client 

**Data Genration**
The data generation part is mocking a POS terminal which generates transaction data. This includes a normal stream of transaction data as well as some retained messages for data calculated for an time frame or something similiar. This Data could look like this: 
```json
{
  "id": "123456789",
  "timestamp": "2025-12-03T14:32:00Z",
  "signature": "sha256:1a2b3c", 
  "items": [
    {"name": "A", "qty": 2, "net": 3.00, "vat": 7},
    {"name": "B", "qty": 1, "net": 2.80, "vat": 19}
  ],
  "total_gross": 6.20,
  "payment_method": "cash",
  "cancellation_flag": false,
  "cashier_id": "maxmustermann"
}
```

**The Broker**
The broker is a MQTT Broker that has the addition of using PBAC (Policy-Based Access Control) policies to control access to topics and messages. In Our case we are deploying the HiveMQ Broker with the [HivePBAC extension](https://github.com/ZODIAC-Project/HiveZODIAC). 

**The MCP Server**
TODO
**The LLM**
(This LLM can also be just an endpoint in the client. Ideally we dont want to deploy our own)The LLM is used to analyse a human readable request and extract the relevant information from it. In our case the goal of the request and the Purpose are most importand. 

**The POS-Client**
The client simulates a a POS terminal that generates sample receipts and sends them to a LLM endpoint. It can be configured to send a number of messages or retained messages.


