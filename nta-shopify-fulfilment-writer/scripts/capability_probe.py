#!/usr/bin/env python3
from shopify_fulfilment_api import probe_capabilities


def main():
    result = probe_capabilities(live=True)
    safe = {
        "configured": result.get("configured"),
        "api_version": result.get("api_version"),
        "token_mode": result.get("token_mode"),
        "fulfilment_read_adapter_verified": result.get("fulfilment_read_adapter_verified"),
        "fulfilment_create_adapter_verified": result.get("fulfilment_create_adapter_verified"),
        "inventory_read_adapter_verified": result.get("inventory_read_adapter_verified"),
        "scopes": result.get("scopes", []),
        "errors": result.get("errors", []),
    }
    print("CAPABILITY_PROBE: read-only; no Shopify mutations")
    for key, value in safe.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
