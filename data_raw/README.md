---
pretty_name: X5 RetailHero Uplift Modelling
task_categories:
  - tabular-classification
tags:
  - finance
configs:
  - config_name: clients
    data_files: data/clients.csv.gz
  - config_name: products
    data_files: data/products.csv.gz
  - config_name: purchases
    data_files: data/purchases.csv.gz
  - config_name: uplift_train
    data_files: data/uplift_train.csv.gz
  - config_name: uplift_test
    data_files: data/uplift_test.csv.gz
---

https://ods.ai/competitions/x5-retailhero-uplift-modeling