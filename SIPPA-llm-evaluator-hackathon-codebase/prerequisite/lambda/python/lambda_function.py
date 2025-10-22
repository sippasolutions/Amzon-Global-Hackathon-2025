from web_search import web_search
from fetch_data import fetch_data


def get_named_parameter(event, name):
    if name not in event:
        return None

    return event.get(name)


def lambda_handler(event, context):
    print(f"Event: {event}")
    print(f"Context: {context}")

    extended_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    resource = extended_tool_name.split("___")[1]

    print(resource)

    if resource == "fetch_data":
        """
        AWS Lambda entry point.
        Expects event = { "data_source": "s3://bucket/file.pdf" } or HTTP body with key "data_source".
        """
        data_source = get_named_parameter(event=event, name="data_source")

        if not data_source:
            return {
                "statusCode": 400,
                "body": "❌ Please provide data_source",
            }

        try:
            raw_text, formatted_text, meta_data = fetch_data(data_source)
        except Exception as e:
            print(e)
            return {
                "statusCode": 400,
                "body": f"❌ {e}",
            }

        return {
            "statusCode": 200,
            "body": {"raw_text": raw_text, "formatted_text": formatted_text, "meta_data": meta_data},
        }


    elif resource == "web_search":
        keywords = get_named_parameter(event=event, name="keywords")
        region = get_named_parameter(event=event, name="region") or "us-en"
        max_results = get_named_parameter(event=event, name="max_results") or 5

        if not keywords:
            return {
                "statusCode": 400,
                "body": "❌ Please provide keywords for search",
            }

        try:
            search_results = web_search(
                keywords=keywords, region=region, max_results=int(max_results)
            )
        except Exception as e:
            print(e)
            return {
                "statusCode": 400,
                "body": f"❌ {e}",
            }

        return {
            "statusCode": 200,
            "body": f"🔍 Search Results: {search_results}",
        }

    return {
        "statusCode": 400,
        "body": f"❌ Unknown toolname: {resource}",
    }
