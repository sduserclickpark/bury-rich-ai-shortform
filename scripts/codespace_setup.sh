#!/bin/bash
# GitHub Codespaces(무료 테스트 환경) 최초 1회 설치
set -e
sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg fonts-nanum
pip install --no-cache-dir -r requirements.txt
