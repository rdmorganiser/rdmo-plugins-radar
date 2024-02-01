#!/bin/bash

git clone https://$GITHUB_TOKEN@github.com/rdmorganiser/rdmo.git
# need rdmo only for testing/config/settings
git clone https://$GITHUB_TOKEN@github.com/rdmorganiser/rdmo-app.git

cd rdmo-app
python3 -m venv env
source env/bin/activate
pip install --upgrade pip setuptools
pip install rdmo"[allauth]"

# install and set-up plugin
cd ..
pip install .
cp rdmo_radar/sample.local.py rdmo-app/config/settings/local.py
PLUGIN=$(basename $(pwd))
PLUGIN_NAME="${PLUGIN/rdmo-plugins-/}"

# set up rdmo-app settings
# write to rdmo-app/config/settings/__init__.py
cp rdmo/testing/config/settings/* rdmo-app/config/settings
cd rdmo-app
# set up instance
# python manage.py download_vendor_files  # download front-end vendor files
python manage.py migrate                # initializes the database
python manage.py setup_groups           # optional: create groups with different permissions

python manage.py loaddata -v 2 "../rdmo/testing/fixtures/users.json"
python manage.py loaddata -v 2 ../rdmo/testing/fixtures/*

python manage.py check

# test PROJECT_EXPORTS setting
PROJECT_EXPORTS=$(python manage.py print_settings -f PROJECT_EXPORTS --format=value)
echo "Testing for presence of setting in django settings"
if [[ $PROJECT_EXPORTS == *"$PLUGIN_NAME"* ]]; then
  echo "Plugin $PLUGIN_NAME is in PROJECT_EXPORTS.\n\t${PROJECT_EXPORTS}"
else
    echo "Plugin $PLUGIN_NAME is not in PROJECT_EXPORTS.\n\t${PROJECT_EXPORTS}"
    exit 1
fi

# test PROJECT_IMPORTS setting
PROJECT_IMPORTS=$(python manage.py print_settings -f PROJECT_IMPORTS --format=value)
echo "Testing for presence of setting in django settings"
if [[ $PROJECT_IMPORTS == *"$PLUGIN_NAME"* ]]; then
  echo "Plugin $PLUGIN_NAME is in PROJECT_IMPORTS.\n\t${PROJECT_IMPORTS}"
else
    echo "Plugin $PLUGIN_NAME is not in PROJECT_IMPORTS.\n\t${PROJECT_IMPORTS}"
    exit 1
fi
