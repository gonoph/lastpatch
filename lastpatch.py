#!/usr/bin/env python3.9

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

"""Obtain CSV output of the last patch time from RHEL servers

requirements:
    dateparser

This script uses the Satellite API to ultimately create a CSV file that has the
last patch date and time for a selection of RHEL servers.

Default output file: /tmp/last_patch.csv

The 1st line will be the header, and the next lines will be CSV data.

Because Satellite uses x509, this script attempts to conform to the same
command line switches as curl.

All output is to stderr, except when listing jobs, which outputs a SHELL
VARIABLE assignment.

"""

import argparse
import sys
import ssl
import urllib.request
import json
import re
from collections import namedtuple
import dateparser
import time

# define the arguments we accept
parser = argparse.ArgumentParser()
parser.add_argument("-k", "--insecure", help="do not validate the server x509 certificate", action='store_true')
parser.add_argument('-o', '--output', help='output report (default: /tmp/last_patch.csv)', default='/tmp/last_patch.csv')
parser.add_argument("-p", "--port", help="satellite server port (default: 443)", type=int, default=443)
parser.add_argument("-s", "--server", help="satellite server host", required=True)
parser.add_argument("-u", "--user", help="username:password auth for Satellite", required=True)
parser.add_argument("-v", "--verbosity", help="increase output verbosity", action="count", default=0)
parser.add_argument("--capath", help="a path to a directory of hashed certificate files")
parser.add_argument("--cafile", help="a single file containing a bundle of CA certificates")
parser.add_argument("--location-id", help='the location id to use (default: none)', type=int, default=None)
parser.add_argument("--organization-id", help='the organization id to use (default: 1)', type=int, default=1)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('-c', '--create', help="create job with query (default: *)", default='*', type=str, nargs='?')
group.add_argument('-l', '--list', help='list last run jobs from job template', action='store_true')
group.add_argument('-j', '--job', help='parse job id')
args = parser.parse_args()

# output routines for errors, warnings, info, and debugging

def error(info, **kwargs):
    '''Take a string and uses kwargs to format it for output to stderr. Then exit the program.'''
    print(info.format(**kwargs), file=sys.stderr)
    sys.exit(1)

def warn(info, **kwargs):
    '''Take a string and uses kwargs to format it for output to stderr.'''
    print(info.format(**kwargs), file=sys.stderr)

def verbose(info, verbosity, **kwargs):
    '''Test the verbosity, and then take a string and uses kwargs to format it for output to stderr.'''
    global args
    if args.verbosity > verbosity:
        print('#' * (verbosity+1) + ' ' + info.format(**kwargs), file=sys.stderr)

def debug4(info, **kwargs):
    '''Based on verbosity 5, take a string and uses kwargs to format it for output to stderr.'''
    verbose(info, 4, **kwargs)

def debug3(info, **kwargs):
    '''Based on verbosity 4, take a string and uses kwargs to format it for output to stderr.'''
    verbose(info, 3, **kwargs)

def debug2(info, **kwargs):
    '''Based on verbosity 3, take a string and uses kwargs to format it for output to stderr.'''
    verbose(info, 2, **kwargs)

def debug(info, **kwargs):
    '''Based on verbosity 2, take a string and uses kwargs to format it for output to stderr.'''
    verbose(info, 1, **kwargs)

def info(info, **kwargs):
    '''Based on verbosity 1, take a string and uses kwargs to format it for output to stderr.'''
    verbose(info, 0, **kwargs)

class JsonTupleEncoder(json.JSONEncoder):
    '''This class is to help encode a collection of namedtuples back into json'''
    def encode(self, obj):
        if isinstance(obj, tuple) and hasattr(obj, '_asdict'):
            return json.JSONEncoder.encode(self, obj._asdict())
        return json.JSONEncoder.encode(self, obj)

class Converters:
    '''This class is a collection of methods to help convert data from one form to another.'''

    def obj2binary(self, data):
        '''This method converts data to a byte string, or None.

            The request object used for HTTPS requests expects the data payload
            to be None or a byte stream.

            Parameters
            ----------
            data : obj
                The data to be converted.
                Byte data is returned.
                String data is coded to utf-8.
                Other data is converted to a json encoded as bytes.

            Returns
            -------
            bytes
                the data as encoded as bytes
        '''
        
        if not data:
            return None
        if type(data) is bytes:
            return data
        if type(data) is not str:
            data = json.dumps(data, cls=JsonTupleEncoder)
        if type(data) is str:
            data = data.encode('utf-8')
        return data

    def json2tuple(self, json):
        '''This method converts a dictionary as what a json object would
            represent and recursively converts it to a namedtuple for easier referencing in
            the program and cleaner string representation via debugging (author's
            opinion).
        '''
        if isinstance(json, list) or isinstance(json, tuple):
            nl = list()
            for value in json:
                nl.append(self.json2tuple(value))
            return nl
        if isinstance(json, dict):
            for key, value in json.items():
                debug4('key={key}, valueType={vt}', key=key, vt=type(value))
                json[key] = self.json2tuple(value) 
            return namedtuple('Json', json.keys())(**json)

        return json

    def fromjson(self, obj):
        '''This method converts a byte string or a filepointer open for reading in to a dictionary representing a json object'''
        if hasattr(obj, 'read'):
            return self.json2tuple(json.load(obj))
        return self.json2tuple(json.loads(obj))

    def _rpmlast2csv(self, hn, spaces, pkg):
        '''This is a private method used in a lambda to convert unstructured known output into CSV output.

            This routine ingests a single line of the output of:
                rpm -qa --last
            to create 3 fields:
                1. Hostname
                2. package name, version, epoc, arch
                3. formated date-time that is compatible with Excel and Google Sheets

            Parameters
            ----------
            hn : str
                the hostname that belongs to the current output being parsed.
            spaces : compiled regular expression
                the compiled re in order to speed up matching
            pkg : str
                the unstructured output from the command above

            Returns
            -------
            str
                a line of CSV formatted data
        '''
        pkg = spaces.sub(' ', pkg)
        spl = pkg.split(' ')
        pkg = spl.pop(0)
        dt = ' '.join(spl)
        dt = dateparser.parse(dt)
        if dt is None:
            dt = dateparser.parse('now')
        
        dt = dt.strftime('%Y-%m-%dT%H:%M:%S')

        return '"{hn}","{pkg}","{dt}"'.format(hn=hn, pkg=pkg, dt=dt)

    def output2csv(self, hn, output):
        '''This method converts a buffer of string output to lines of CSV formatted data using _rpmlast2csv above'''

        lines = output.split('\n')
        debug3('output lines ({lines}) and size ({size})', lines=len(lines), size=len(output))
        # filter out blank lines
        lines = filter(lambda x: x, lines)
        # compile the regex for faster matching
        spaces = re.compile(' +')
        lines = map(lambda x: self._rpmlast2csv(hn, spaces, x), lines)
        lines = list(lines)
        output = "\n".join(lines)
        debug3('converted lines ({lines}) and size ({size})', lines=len(lines), size=len(output))
        return output

class SatelliteService:
    '''This class represents the various APIs needed to create, query, and capture the output of Satellite jobs

        Attributes
        ----------
            auth : HTTPBasicAuthHandler
                auth handler with a HTTPPasswordMgrWithPriorAuth mgr for default realm
            ctx  : HTTPSHandler
                SSL context handler with default context or unverified context depending on cmdline args
            converts : Converters
                the converters used to transform various data
            url : str
                the base uri formated as a URI for all our API calls
            opener : request HTTP Opener
                opener defined with the SSL and Auth handler above

            Methods
            -------
            get_request(api, method='GET', data=None, headers={})
                returns the HTTPS request for the given API end point.

            get_job_template()
                returns a single result for the job template needed to run commands.

            get_jobs()
                list all matching "rpm" jobs as CSV and output a line to act as a SHELL VARIABLE assignment.

            get_single_job(jobid)
                writes out CSV data to the report file from a given job id

            prep_output()
                prepares the report file for writing by truncating it

            check_job_status(task)
                checks the status of a task using the private method below.

            _check_job_status(task)
                recursively retries to check the status of a task until timeout or task stops.

            create_job()
                Using a job_template, creates a task, then calls get_single_job() for the output.
    '''

    def _create_auth(self):
        debug2('Creating auth...')
        a = self.args.user.split(':')
        user = a.pop(0)
        pw = ':'.join(a)
        mgr = urllib.request.HTTPPasswordMgrWithPriorAuth()
        mgr.add_password(realm=None, uri=self.url, user=user, passwd=pw, is_authenticated=True)
        a = urllib.request.HTTPBasicAuthHandler(mgr)
        debug3('url={url}, user={user}, pw={pw}', url=self.url, user=user, pw=pw)
        return a 

    def _create_ctx(self):
        debug2('Creating ssl ctx...')
        if args.insecure:
            debug3('insecure ctx')
            ctx = ssl._create_unverified_context()
        else:
            ctx = ssl.create_default_context(cafile=self.args.cafile, capath=self.args.capath)
        return urllib.request.HTTPSHandler(context=ctx)

    def __init__(self, args):
        debug('Satellite Service creating...')
        self.args = args

        self.converters = Converters()

        if args.port != 443:
            fmt="https://{args.server}:{args.port}/"
        else:
            fmt="https://{args.server}/"
        self.url=fmt.format(args=args)

        self.auth = self._create_auth()
        self.ctx  = self._create_ctx()
        self.opener = urllib.request.build_opener(self.ctx, self.auth)
        urllib.request.install_opener(self.opener)

        debug("api url: {url}", url=self.url)

    def get_request(self, api, method='GET', data=None, headers={}):
        '''returns the HTTPS request for the given API end point.

            Performs several steps:
                converts data to a byte stream
                adds a json header to the headers
                appends the api endpoint to the base url

            Parameters
            ----------
            api : str
                API end point to append to the base url
            method : str
                the HTTP method to use (GET, POST, HEAD)
            data : bytes or None
                the data to send as a post, json encoded as bytes
            headers : dict
                additional headers to send as part of the request

            Returns
            -------
            urllib.request.Request
                object that represents the request that will be used to interact with the API
        '''

        headers['Content-Type']='application/json'
        data = self.converters.obj2binary(data)
        url = self.url + api
        debug3('request: url={url}, method={method}, data={data}, headers={headers}', url=url, method=method, data=data, headers=headers)
        return urllib.request.Request(url=url, data=data, headers=headers, method=method)
    
    def get_job_template(self):
        '''returns a single result for the job template needed to run commands.

            Searches for the job template as described by:
                job_category = Commands and name = "Run Command - Script Default"

            Parameters
            ----------
            None :
                No parameters

            Returns
            -------
            namedtuple
                returns a namedtuple that represents a job_template
        '''

        info('Getting request templates id')
        data=dict(
            per_page=1,
            search='job_category = Commands and name = "Run Command - Script Default"'
        )
        req = self.get_request('api/job_templates', data=data)
        resp = urllib.request.urlopen(req)
        template = self.converters.fromjson(resp)
        debug3('json data: {json}', json=template)
        if template.results:
            template = template.results.pop()
        else:
            raise ValueError('Unable to find template_id')

        debug('Found template: {template}', template=template)

        return template

    def get_jobs(self):
        '''list all matching "rpm" jobs as CSV and output a line to act as a SHELL VARIABLE assignment.

            lists all the jobs using default paging that match the description:
                Run rpm -qa --last

            Parameters
            ----------
            None :
                No parameters

            Returns
            -------
            None
                Does not return a value, but outputs CSV to stderr, and a SHELL VARIABLE assignment line.
        '''

        info("Getting list of jobs")
        data=dict(
            search='description="Run rpm -qa --last"',
            order='start_at DESC'
        )
        req = self.get_request('api/job_invocations', data=data)
        resp = urllib.request.urlopen(req)

        jobs = self.converters.fromjson(resp)
        debug3('json data: {json}', json=jobs)
        fmt=['id', 'description', 'status', 'success_fail_total', 'date_time']
        print('"' + '","'.join(fmt) + '"')
        fmt='"{' + '}","{'.join(fmt) + '}"'

        if not jobs or not jobs.results:
            raise ValueError('Unable to locate any jobs of type: {data}'.format(data=data))

        for job in jobs.results:
            print(fmt.format(
                    id=job.id,
                    description=job.description, 
                    status=job.status_label,
                    success_fail_total="{s}/{f}/{t}".format(s=job.succeeded, f=job.failed, t=job.total),
                    date_time=job.start_at
            ))

        return jobs

    def get_single_job(self, jobid):
        '''writes out CSV data to the report file from a given job id

            performs several tasks:
                obtains info on that jobid
                checks the job status and loops until it is stopped
                cycles through the hosts output
                converts the host output to CSV

            Parameters
            ----------
            jobid : int
                the job id needed to extract and convert the ouput to CSV

            Returns
            -------
            None
                Does not return a value, but creates a report file.
        '''

        info("Getting info for single job id: {jobid}", jobid=jobid)
        req = self.get_request('api/job_invocations/{job}'.format(job=jobid))
        resp = urllib.request.urlopen(req)

        job = self.converters.fromjson(resp)
        debug3('json data: {json}', json=job)
        hosts = map(lambda x: (x.name, x.id), job.targeting.hosts)
        hosts = dict(hosts)
        host_ids = map(lambda x: (str(x.id), x.name), job.targeting.hosts)
        host_ids = dict(host_ids)
        
        debug2('hosts: {hosts}', hosts=hosts)

        status = self.check_job_status(job.task)
        debug2('{status}', status=status)

        with self.prep_output() as csv:

            print('"hostname","package name","last updated"', file=csv)

            for hn, hid in hosts.items():
                req = self.get_request('api/job_invocations/{job}/hosts/{hostid}'.format(job=jobid, hostid=hid))
                resp = urllib.request.urlopen(req)
                output = json.load(resp)
                if not output or 'output' not in output or not output['output']:
                    warn("WARN: Missing output for {req}", req=req.full_url)
                    output = ''
                else:
                    output = filter(lambda x: x['output_type'] == 'stdout', output['output'])
                    output = list(output).pop(0)['output']
                    output = self.converters.output2csv(hn, output)

                print(output, file=csv)

    def prep_output(self):
        '''prepares the report file for writing by truncating it.'''

        info('Writing to file: {args.output}', args=self.args)
        return open(self.args.output, 'w')

    def check_job_status(self, task):
        '''creates the request used for _calling _check_job_status()'''

        info('Checking status of {task.id}', task=task)
        req = self.get_request('foreman_tasks/api/tasks/{task.id}'.format(task=task))
        return self._check_job_status(req)

    def _check_job_status(self, req, old_status = {}, max_stale = 15, cur_stale = 0):
        '''recursively retries to check the status of a task until timeout or task stops.'''

        resp = urllib.request.urlopen(req)
        status = self.converters.fromjson(resp)
        
        debug('{status.id}, state={status.state}, duration={status.duration}, progress={status.progress}', status=status)

        if status.state == 'stopped':
            return status

        if old_status == status:
            if cur_stale >= max_stale:
                raise TimeoutError(f'Ran out of time waiting for status of {req.full_url}, max_stale={max_stale}')
            cur_stale+=1
        else:
            cur_stale = 0
        
        time.sleep(1)
        return self._check_job_status(req, status, max_stale, cur_stale)
        
    def create_job(self):
        '''creates a job using a job_template, then calls get_single_job() for the output.'''

        info('Creating job witih query: {args.create}', args=self.args)
        template = self.get_job_template()
                # inputs=dict(command='id'),
        data = dict(
            organization_id = args.organization_id,
           job_invocation = dict(
                job_template_id=template.id,
                inputs=dict(command="rpm -qa --last"),
                targeting_type='static_query',
                search_query=self.args.create
            )
        )
        if args.location_id:
            data['location_id'] = args.location_id
        data=json.dumps(data, cls=JsonTupleEncoder)
        req = self.get_request('api/job_invocations', method='POST', data=data)
        resp = urllib.request.urlopen(req)
        task = self.converters.fromjson(resp)
        info('Created job: {task.id}', task=task)
        debug2('Task info: {task}', task=task)
        
        self.get_single_job(task.id)

info("Last Patch starting")

service = SatelliteService(args)

if args.list:
    jobs = service.get_jobs()
    warn('LAST_JOB_ID={job.id}', job=jobs.results[0])
    sys.exit(0)

if args.job:
    service.get_single_job(args.job)
    sys.exit(0)

if not args.create:
    args.create = '*'

if args.create:
    service.create_job()
    sys.exit(0)
