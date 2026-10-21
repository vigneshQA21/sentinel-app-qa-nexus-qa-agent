Put one file per shipment here, named after the HAWB (e.g. `UNF1005.yaml`).
Each key is a shipper field from `config/selectors.yaml`; the agent types the value into
Nexus, saves it and re-reads it to confirm. Example:

```yaml
shipper_city: Tiruppur
consignee_name: Nordic Retail AB
```
