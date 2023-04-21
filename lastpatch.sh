#!/bin/sh
# Copyright 2023, Billy Holmes

# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.

# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.

REPORT=/tmp/last_patch.csv

errexit() {
	echo "Error getting last patch:" "$@" 1>&2
	exit 1
}

header() {
	tee -a $REPORT <<< "$@"
}

chkblank() {
	test -z "$1" && errexit "$2"
}

#truncate the file

>$REPORT

TEMPLATE=$(hammer --no-headers job-template list --search 'job_category = Commands and name = "Run Command - Script Default"' --per-page 1)
read TEMPLATE_ID JUNK <<< "$TEMPLATE"
chkblank "$TEMPLATE_ID" "Unable to get template id!"

header "# Template: $TEMPLATE"

ID=$(hammer --output yaml job-invocation create --job-template-id $TEMPLATE_ID --search-query '*' --organization-id 1 --location-id 2  --inputs "command=rpm -qa --last" | grep :id: |cut -d' ' -f 2 | xargs echo)
chkblank "$ID" "Unable to get job id for template: $TEMPLATE"

JOB_INFO=$(hammer --output csv --no-headers job-invocation info --id=$ID --fields description)
chkblank "$JOB_INFO" "Unable to get job info for job: $ID"

header "# $JOB_INFO"

HOSTS=$(hammer --output yaml job-invocation info --id=$ID --fields hosts | grep Name: | cut -d: -f 2- | xargs echo)
chkblank "$HOSTS" "Unable to get hosts for job: $ID"

header "# Hosts: $HOSTS"
header "# Creating $REPORT @ $(date)"

echo '"hostname","package name","last patch in UTC"' >> $REPORT

for host in $HOSTS ; do
	hammer job-invocation output --id $ID --host $host | grep -v '^Exit status: ' | tr -s ' ' | while read PKG DATE ; do
		DATE=$(TZ=UTC date -d "$DATE" '+%Y-%m-%dT%H:%M:%S')
		echo "\"$host\",\"$PKG\",$DATE"
	done
done >> $REPORT
