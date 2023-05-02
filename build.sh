#!/bin/bash

pluginVersion=$(python3 version.py)

git archive plugin.video.piped-$(pluginVersion).zip

