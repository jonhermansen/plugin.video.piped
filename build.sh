#!/bin/bash

source .env.default
source .env

./generate_metadata.py

zip -r ${pluginName}-${pluginVersion}.zip .
