#!/bin/bash

git clone https://$GITHUB_TOKEN@github.com/rdmorganiser/rdmo.git
# need rdmo only for testing/config/settings
git clone https://$GITHUB_TOKEN@github.com/rdmorganiser/rdmo-app.git

cd rdmo-app || exit 1
python3 -m venv env
source env/bin/activate
pip install --upgrade pip setuptools
pip install rdmo"[allauth]"

# install and set-up plugin
cd - || exit 1
pip install .
cp rdmo_radar/sample.local.py rdmo-app/config/settings/local.py
PLUGIN="$(basename "$(pwd)")"
PLUGIN_NAME="${PLUGIN/rdmo-plugins-/}"

# set up rdmo-app settings
# write to rdmo-app/config/settings/__init__.py
cp rdmo/testing/config/settings/* rdmo-app/config/settings
cd rdmo-app || exit 1
mkdir vendor
# set up instance
# python manage.py download_vendor_files  # download front-end vendor files
python manage.py migrate                # initializes the database
python manage.py setup_groups           # optional: create groups with different permissions

python manage.py loaddata -v 2 "../rdmo/testing/fixtures/users.json"
python manage.py loaddata -v 2 ../rdmo/testing/fixtures/*

python manage.py check

# function for testing presence of plugin name in a certain django setting
test_if_settings_contain_plugin () {
  SETTING_NAME=$1
  SETTING_VALUE="$(python manage.py print_settings -f $SETTING_NAME --format=value)"
  echo "Testing if the value of the django setting ${SETTING_NAME} contains $2"
  if [[ ${SETTING_VALUE} == *"$2"* ]]; then
    echo -e "OK, Plugin $2 is in ${SETTING_NAME}.\n\t${SETTING_VALUE}"
  else
      echo -e "ERROR, Plugin $2 is not in ${SETTING_NAME}.\n\t${SETTING_VALUE}"
      exit 1
  fi
}

test_if_settings_contain_plugin "PROJECT_EXPORTS" $PLUGIN_NAME

test_if_settings_contain_plugin "PROJECT_IMPORTS" $PLUGIN_NAME
