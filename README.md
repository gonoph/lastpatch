# lastpatch
Script to interact with the Satellite API to extract last patch data from RHEL hosts

## Background

This script was created to duplicate a similar feature that was found in Satellite 5.

[How can I generate a report for when patches were installed on Satellite clients in a specific date range?][1]

Also, it was drawn on another solution, but it wasn't exactly what I needed.

[How to generate a list of applied erratum from all the content hosts][2]

Drawing inspiration on that, I crafted up a quick and dirty shell script: [lastpatch.sh](lastpatch.sh)

[1]: https://access.redhat.com/solutions/1241653
[2]: https://access.redhat.com/solutions/7001207

## Goals

The shell script I wrote felt fragile, and a little slow as it needed to call the hammer command multiple times. There also wasn't a lot of customization.

* Make it more robust
* Allow some customization
* Add the ability to parse an existing job
* Make it a little faster

## Install

Requires:
* Python 3.9
* dateparser

If you have pip installed, you can issue:

```bash
pip3.9 install -r requirements.txt
```

You may only need to issue `pip` on the command line, but if you have multiple versions like me, you want to be explict where pip installs things.

Next you will need some information:
* the Satellite URL
* Satellite username and password ([I recommend a Personal Access Token][3])
* The permissions on the Satellite to query jobs or run jobs

[3]: https://access.redhat.com/documentation/en-us/red_hat_satellite/6.11/html/api_guide/chap-red_hat_satellite-api_guide-authenticating_api_calls#Authenticating_API_Calls-PAT_Authentication_Overview

## Usage

So, for this example, I am using admin, but that's just for my demo system. Please don't use admin in your production environment.

```
usage: lastpatch.py [-h] [-k] [-o OUTPUT] [-p PORT] -s SERVER -u USER [-v] [--capath CAPATH] [--cafile CAFILE] [--location-id LOCATION_ID]
                    [--organization-id ORGANIZATION_ID] (-c [CREATE] | -l | -j JOB)

optional arguments:
  -h, --help            show this help message and exit
  -k, --insecure        do not validate the server x509 certificate
  -o OUTPUT, --output OUTPUT
                        output report (default: /tmp/last_patch.csv)
  -p PORT, --port PORT  satellite server port (default: 443)
  -s SERVER, --server SERVER
                        satellite server host
  -u USER, --user USER  username:password auth for Satellite
  -v, --verbosity       increase output verbosity
  --capath CAPATH       a path to a directory of hashed certificate files
  --cafile CAFILE       a single file containing a bundle of CA certificates
  --location-id LOCATION_ID
                        the location id to use (default: none)
  --organization-id ORGANIZATION_ID
                        the organization id to use (default: 1)
  -c [CREATE], --create [CREATE]
                        create job with query (default: *)
  -l, --list            list last run jobs from job template
  -j JOB, --job JOB     parse job id
```
  
You will need at least three (3) parameters:
1. (-s server) Satellite Server
2. (-u user:pass) username and password (Personal Access Token or password)
3. a command of one of the following:
   1. (-l) list last ran jobs using our job template
   2. (-c query) create a job with the given host query (defaults to * - aka everything)
   3. (-j) parse the output from the given job id

You can increase the verbosity of the output of the script by issuing multiple -v (ex: -vvv) on the command line.

### List Command

The List command will query the most recent "rpm -qa --last" Satellite jobs with the default paging (20 per result).

It will then show the result to stdout in CSV format, and finally output a line to STDERR that can be used as a SHELL VARIABLE assignment which has the last job id.

### Create Command

The Create command will find the default Run Command job template, and create a task with essentially:
* the host query of hosts to run the job
* the command: `rpm -qa --last`
* limited to the organization and location (default org is 1)

Then it will call the Job command.

### Job Command

The Job command will query Satellite for information on this job id. It does the following:
* obtain the job metadata
* patient wait for the job to finish if it has not already
* extract the hosts that ran the job
* query the Satellite API for the output of each host for that job
* convert the output to a CSV and write it to a file

Be default, I'm using `/tmp/last_patch.csv` as the default report name. You can change this via a command line option.

## Examples

### Get a list of jobs

```
$ ./lastpatch.py -s satellite.example.com -u admin:MI3A4iz7ugUqpk_x4Y6PhA -v -l
# Last Patch starting
# Getting list of jobs
"id","description","status","success_fail_total","date_time"
"153","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 20:12:09 UTC"
"152","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 17:45:05 UTC"
"151","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:53:01 UTC"
"150","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:48:59 UTC"
"149","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:48:23 UTC"
"148","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:41:28 UTC"
"147","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:40:26 UTC"
"146","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:38:11 UTC"
"145","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 16:37:09 UTC"
"144","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:14:31 UTC"
"143","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:11:03 UTC"
"142","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:10:29 UTC"
"141","Run rpm -qa --last","succeeded","1/0/1","2023-04-21 08:10:02 UTC"
"140","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:07:39 UTC"
"139","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:06:41 UTC"
"138","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:05:56 UTC"
"137","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:04:18 UTC"
"136","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 08:03:19 UTC"
"118","Run rpm -qa --last","succeeded","3/0/3","2023-04-21 00:18:43 UTC"
"117","Run rpm -qa --last","succeeded","3/0/3","2023-04-20 22:34:49 UTC"
LAST_JOB_ID=153
```

### Query and output the result of a job

```
$ ./lastpatch.py -s satellite.example.com -u admin:MI3A4iz7ugUqpk_x4Y6PhA -v -j 153
# Last Patch starting
# Getting info for single job id: 153
# Checking status of cb41ca48-48ba-485f-a3cd-23e948fc2938
# Writing to file: /tmp/last_patch.csv

$ head -n 5 /tmp/last_patch.csv
"hostname","package name","last updated"
"demo1.example.com","python3-pbr-5.8.1-2.el9ap.noarch","2023-04-14T13:06:04"
"demo1.example.com","python3-parsley-1.3-2.el9pc.noarch","2023-04-14T13:06:04"
"demo1.example.com","python3-bindep-2.10.2-3.el9ap.noarch","2023-04-14T13:06:04"
"demo1.example.com","ansible-builder-1.2.0-1.el9ap.noarch","2023-04-14T13:06:04"
```

### Create a new job and extract the output

```
$ ./lastpatch.py -s satellite.example.com -u admin:MI3A4iz7ugUqpk_x4Y6PhA -v -c
# Last Patch starting
# Creating job witih query: *
# Getting request templates id
# Created job: 154
# Getting info for single job id: 154
# Checking status of 94a44ce5-23a9-4d2f-9a86-ec9948b5f8a8
# Writing to file: /tmp/last_patch.csv
```

# Getting Help

DISCLAIMER: I'm a Red Hat Solutions Architect. It's my job to introduce Red Hat customers to Red Hat products, and help them gain the most value from these products. I am not support, nor releasing this as a representative of Red Hat. Thus, I cannot help you use this script in production, development, a PoC, or bake-off situation. I will gladly help you get in contact with someone at Red Hat that CAN help you do these things.

The purpose of this project is to show how you can interact with the Satellite API to gain new capabilities and features that aren't otherwise available out of the box.

If you have other questions or issues with RHEL or Satellite in general, I'll gladly help you reach the correct resource at Red Hat!
