

# OpenAI at Scale: Azure API Management Circuit Breaker and Load Balancing


## Scenario
In this blog post, I will demonstrate how to leverage [Azure API Management](https://learn.microsoft.com/en-us/azure/api-management/api-management-key-concepts) to enhance the resiliency and capacity of your [Azure OpenAI Service](https://learn.microsoft.com/en-us/azure/ai-services/openai/overview).  
Azure API Management is a tool that assists in creating, publishing, managing, and securing APIs. It offers features like routing, caching, throttling, authentication, transformation, and more.  
By utilizing Azure API Management, you can:

* Distribute requests across multiple instances of the Azure OpenAI Service using the [priority-based load balancing technique](https://learn.microsoft.com/en-us/azure/api-management/backends?tabs=bicep#load-balanced-pool), which includes groups with weight distribution inside the group. This helps spread the load across various resources and regions, thereby enhancing the availability and performance of your service.
* Implement the [circuit breaker](https://learn.microsoft.com/en-us/azure/api-management/backends?tabs=bicep#circuit-breaker) pattern to protect your backend service from being overwhelmed by excessive requests. This helps prevent cascading failures and improves the stability and resiliency of your service. You can configure the circuit breaker property in the backend resource and define rules for tripping the circuit breaker, such as the number or percentage of failure conditions within a specified time frame and a range of status codes indicating failures.

![apim](/readme/diagram-apim.png)  
Diagram 1: API Managment with circuit breaker implementation.

> **Important**: Backends in lower priority groups will only be used when all backends in higher priority groups are unavailable because circuit breaker rules are tripped.
> 
![circuit-breaker](/readme/diagram-circuit-breaker.png)  
Diagram 2: API Managment with circuit breaker in action.  

---
In the following section I will guide you through circuit breaker deployment with API Managment and Azure Open AI services. you can use the same solution with native OpenAI service.

## Prerequisites
* If you don't have an [Azure subscription](https://learn.microsoft.com/en-us/azure/guides/developer/azure-developer-guide#understanding-accounts-subscriptions-and-billing), create a [free account](https://azure.microsoft.com/free/?WT.mc_id=A261C142F) before you begin.
* Use the Bash environment in [Azure Cloud Shell](https://learn.microsoft.com/en-us/azure/cloud-shell/overview). For more information, see [Quickstart for Bash in Azure Cloud Shell](https://learn.microsoft.com/en-us/azure/cloud-shell/quickstart).
* If you prefer to run CLI reference commands locally, [install](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) the Azure CLI.
* If you're using a local installation, sign in to the Azure CLI by using the [az login](https://learn.microsoft.com/en-us/cli/azure/reference-index#az-login) command. To finish the authentication process, follow the steps displayed in your terminal. For other sign-in options, see [Sign in with the Azure CLI](https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli).
* if you don't have Azure API Management, [create a new instance](https://learn.microsoft.com/en-us/azure/api-management/get-started-create-service-instance).
* [Azure OpenAI Services](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource?pivots=web-portal) for the backend pool, each service should have the **same model deployed with the same name and version** across all the services.

---
## Step I: Provision Azure API Management Backend Pool (bicep): 

### Bicep CLI
Install or Upgrade Bicep CLI.
```bash
# az bicep install
az bicep upgrade
```
### Deploy the Backend Pool using Bicep
Login to Azure.
```bash
az login
```

> **Important**: Update the names of the backend services in the [deploy.bicep](/deploy.bicep) file.  

Create a deployment at resource group from a remote template file, update the parameters in the file.
```bash
az deployment group create --resource-group <resource-group-name> --template-file <path-to-your-bicep-file> --name apim-deployment
```
> **Note**: You can learn more about the bicep backend resource [Microsoft.ApiManagement service/backends](https://learn.microsoft.com/en-us/azure/templates/microsoft.apimanagement/service/backends?pivots=deployment-language-bicep).
> Also about the [CircuitBreakerRule](https://learn.microsoft.com/en-us/azure/templates/microsoft.apimanagement/service/backends?pivots=deployment-language-bicep#circuitbreakerrule)
> **Note**: The following warning may be displayed when running the above command:
> ```bash
> /path/to/deploy.bicep(102,3) : Warning BCP035: The specified "object" declaration is missing the following required properties: "protocol", "url". If this is an inaccuracy in the documentation, please report it to the Bicep Team. [https://aka.ms/bicep-type-issues]
> ```

Output:
```json
{
  "id": "<deployment-id>",
  "location": null,
  "name": "apim-deployment",
  "properties": {
    "correlationId": "754b1f5b-323f-4d4d-99e0-7303d8f64695",
    .
    .
    .
    "provisioningState": "Succeeded",
    "templateHash": "8062591490292975426",
    "timestamp": "2024-09-07T06:54:37.490815+00:00",
  },
  "resourceGroup": "azure-apim",
  "type": "Microsoft.Resources/deployments"
}
```

![APIM Backends](/readme/apim-backends.png)


> **Note**: To view failed operations, filter operations with the 'Failed' state.
> ```bash
> az deployment operation group list --resource-group <resource-group-name> --name apim-deployment --query "[?properties.provisioningState=='Failed']"
> ```

The following is the [deploy.bicep](/deploy.bicep) backend circuit breaker and load balancer configuration:
```bicep
resource apiManagementService 'Microsoft.ApiManagement/service@2023-09-01-preview' existing = {
  name: apimName
}

resource backends 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = [for (name, i) in backendNames: {
  name: name
  parent: apiManagementService
  properties: {
    url: 'https://${name}.openai.azure.com/openai'
    protocol: 'http'
    description: 'Backend for ${name}'
    type: 'Single'
    circuitBreaker: {
      rules: [
        {
          acceptRetryAfter: true
          failureCondition: {
            count: 1
            interval: 'PT10S'
            statusCodeRanges: [
              {
                min: 429
                max: 429
              }
              {
                min: 500
                max: 503
              }
            ]
          }
          name: '${name}BreakerRule'
          tripDuration: 'PT10S'
        }
      ]
    }
  }
}]
```
And another for the backend pool:
```bicep
resource aoailbpool 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = {
  name: 'openaiopool'
  parent: apiManagementService
  properties: {
    description: 'Load balance openai instances'
    type: 'Pool'
    pool: {
      services: [
        {
          id: '/backends/${backendNames[0]}'
          priority: 1
          weight: 1
        }
        {
          id: '/backends/${backendNames[1]}'
          priority: 2
          weight: 1
        }
        {
          id: '/backends/${backendNames[2]}'
          priority: 2
          weight: 1
        }
      ]
    }
  }
}
```


---
## Step II: Create the API Management API
> **Note**: The following policy can be used in existing APIs or new APIs. the important part is to set the backend service to the backend pool created in the previous step.

### Option I: Add to existing API
All you need to do is to add the following [set-backend-service](https://learn.microsoft.com/en-us/azure/api-management/set-backend-service-policy) and the [retry](https://learn.microsoft.com/en-us/azure/api-management/retry-policy) policies for activating the Load Balancer with Circuit Breaker module:    
```xml
<set-backend-service id="lb-backend" backend-id="openaiopool" />
```

```xml
<retry condition="@(context.Response.StatusCode == 429)" count="3" interval="1" first-fast-retry="true">
  <forward-request buffer-request-body="true" />
</retry>
```

### Option II: Create new API
#### Add new API

1. Go to your API Management instance.
2. Click on APIs.
3. Click on Add API.
4. Select 'HTTP' API.
5. Giive it a name and set the URL suffix to 'openai'.

![APIM API](/readme/create-api.png)
> **Note**: The URL suffix is the path that will be appended to the API Management URL. For example, if the API Management URL is 'https://apim-ai-features.azure-api.net', the URL suffix is 'openai', and the full URL will be 'https://apim-ai-features.azure-api.net/openai'.
#### Add "catch all" operation
1. Click on the API you just created.
2. Click on the 'Design' tab.
3. Click on Add operation.
4. Set the method to 'POST'.
5. Set the URL template to '/{*path}'.
6. Set the name.
7. Click on 'Save'.

![Add Operation](/readme/add-operation.png)

#### Add the Load Balancer Policy
1. Select the operation you just created.
2. Click on the 'Design' tab.
3. Click on 'Inbound processing' policy button '</>'.
4. Replace the existing policy with [this policy](/policy.xml)
5. Click on 'Save'.

> **Important**: The main policies taking part of the load balancing that will distribute the requests to the backend pool created in the previous step are the following:
> ***set-backend-service***: This policy sets the backend service to the backend pool created in the previous step.
> ```xml
> <set-backend-service id="lb-backend" backend-id="openaiopool" />
> ```
> ***retry***: This policy retries the request if the backend service is unavailable. in case the circuit breaker gets triggered, the request will be retried immidiately to the next available backend service.
> **Important**: The value of `count` should be equal to the number of backend services in the backend pool.
> ```xml
> <retry condition="@(context.Response.StatusCode == 429)" count="3" interval="1" first-fast-retry="true">
>   <forward-request buffer-request-body="true" />
> </retry>
> ```

![Add Policy](/readme/policy.png)

The [policy](/policy.xml) is set up to distribute requests across the backend pool and retry requests if the backend service is unavailable:
```xml
<policies>
    <inbound>
        <base />
        <set-backend-service id="lb-backend" backend-id="openaiopool" />
        <azure-openai-token-limit tokens-per-minute="400000" counter-key="@(context.Subscription.Id)" estimate-prompt-tokens="true" tokens-consumed-header-name="consumed-tokens" remaining-tokens-header-name="remaining-tokens" />
        <authentication-managed-identity resource="https://cognitiveservices.azure.com/" />
        <azure-openai-emit-token-metric namespace="genaimetrics">
            <dimension name="Subscription ID" />
            <dimension name="Client IP" value="@(context.Request.IpAddress)" />
        </azure-openai-emit-token-metric>
        <set-variable name="traceId" value="@(Guid.NewGuid().ToString())" />
        <set-variable name="traceparentHeader" value="@("00" + context.Variables["traceId"] + "-0000000000000000-01")" />
        <set-header name="traceparent" exists-action="skip">
            <value>@((string)context.Variables["traceparentHeader"])</value>
        </set-header>
    </inbound>
    <backend>
        <retry condition="@(context.Response.StatusCode == 429)" count="3" interval="1" first-fast-retry="true">
            <forward-request buffer-request-body="true" />
        </retry>
    </backend>
    <outbound>
        <base />
        <set-header name="backend-host" exists-action="skip">
            <value>@(context.Request.Url.Host)</value>
        </set-header>
        <set-status code="@(context.Response.StatusCode)" reason="@(context.Response.StatusReason)" />
    </outbound>
    <on-error>
        <base />
        <set-header name="backend-host" exists-action="skip">
            <value>@(context.LastError.Reason)</value>
        </set-header>
        <set-status code="@(context.Response.StatusCode)" reason="@(context.LastError.Message)" />
    </on-error>
</policies>
```

---
## Step III: Cofigure Monitoring
1. Go to your API Management instance.
2. Click on 'APIs'.
3. Click on the API you just created.
4. Click on 'Settings'.
5. Scroll down to 'Diagnostics Logs'.
6. Check the 'Override global' checkbox.
7. Add the 'backend-host' and 'Retry-After' headers to log.
8. Click on 'Save'.
> **Note**: The 'backend-host' header is the host of the backend service that the request was actually sent to. The 'Retry-After' header is the time in seconds that the client should wait before retrying the request sent by the Open AI service overriding tripDuration of the [backend circuit breaker](/deploy.bicep) setting.
> **Note**: Also you can add the request and response body to the logs in the 'Advanced Options' section.  

![Add Monitoring](/readme/monitoring-settings.png)

---
## Step IV: Prepare the OpenAI Service

#### Deploy the model 
> **Important**: In order to use the load balancer configuration seamlessly, All the OpenAI services should have the same model deployed. The model should be deployed with the same name and version across all the services.

1. Go to the OpenAI service.
2. Select the 'Model deployments' blade.
3. Click the 'Manage Deployments' button.
4. Configure the model.
5. Click on 'Create'.
6. Repeat the above steps for all the OpenAI services, making sure that the model is deployed with the same name and version across all the services.

![OpenAI Model](/readme/model-deployment.png)

#### Set the Managed Identity
> **Note**: The API Management instance should have the System/User 'Managed Identity' set to the OpenAI service.

1. Go to the OpenAI service.
2. Select the 'Access control (IAM)' blade.
3. Click on 'Add role assignment'.
4. Select the role 'Cognitive Services OpenAI User'.
5. Select the API Management managed identity.
6. Click on 'Review + assign'.
7. Repeat the above steps for **all** the OpenAI services.

![OpenAI Role](/readme/open-ai-iam.png)

---
## Step V: Test the Load Balancer
> **Note**: Calling the API Management API will require the 'api-key' header to be set to the subscription key of the API Management instance.
> ![API Key](/readme/subscription-key.png)

We are going to run the [Chat Completion API](https://learn.microsoft.com/en-us/azure/ai-services/openai/reference#chat-completions) from the OpenAI service through the API Management API. The API Management API will distribute the requests to the backend pool created in the previous steps.


### Run the Python load-test script:
Execute the test python script [main.py](/main.py) to test the load balancer and circuit breaker configuration.
```bash
python main.py --apim-name apim-ai-features --subscription-key APIM_SUBSCRIPTION_KEY --request-max-tokens 200 --workers 5 --total-requests 1000 --request-limit 30
```

#### Explanation:
* `python main.py`: This runs the `main.py` script.
* `--apim-name apim apim-ai-features`: The name of the API Management.
* `--key APIM_SUBSCRIPTION_KEY`: This passes the API subscription key.
* `--request-max-tokens 200`: The maximum number of tokens to generate per request in the completion (optional, as it defaults to 200).
* `--workers 5`: The number of parallel requests to send (optional, as it defaults to 20).
* `--total_requests 1000`: This sets the total number of requests to 1000 (optional, as it defaults to 1000).
* `--request-limit 30`: The number of requests to send per second (optional, as it defaults to 20).
  
> **Note**: You can adjust the values of `--batch_size` and `--total_requests` as needed. If you omit them, the script will use the default values specified in the argparse configuration.

![Testing Window](/readme/testing-green.png)

#### Test Results:
```kql
ApiManagementGatewayLogs
| where OperationId == "chat-completion"
| summarize CallCount = count() by BackendId, BackendUrl
| project BackendId, BackendUrl, CallCount
| order by CallCount desc
| render barchart 
```
![APIM Gateway Logs](/readme/results-bar-chart.png)


## Conclusion
In conclusion, leveraging Azure API Management significantly enhances the resiliency and capacity of Azure OpenAI service by distributing requests across multiple instances and implementing load-balancer with retry/circuit-breaker patterns.  
These strategies improve service availability, performance, and stability. To read more look in [Backends in API Management](https://learn.microsoft.com/en-us/azure/api-management/backends?tabs=bicep).


## References

#### Azure API Management
[Azure API Management terminology](https://learn.microsoft.com/en-us/azure/api-management/api-management-terminology)  
[API Management policy reference](https://learn.microsoft.com/en-us/azure/api-management/api-management-policies)  
[API Management policy expressions](https://learn.microsoft.com/en-us/azure/api-management/api-management-policy-expressions)  
[Backends in API Management](https://learn.microsoft.com/en-us/azure/api-management/backends?tabs=bicep)  
[Error handling in API Management policies](https://learn.microsoft.com/en-us/azure/api-management/api-management-error-handling-policies)  

#### Azure OpenAI
[Azure OpenAI deployment types](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/deployment-types)  
[Azure OpenAI Service quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/openai/quotas-limits)  

#### Azure Tech Community
[AI Hub Gateway Landing Zone accelerator](https://github.com/Azure-Samples/ai-hub-gateway-solution-accelerator)
