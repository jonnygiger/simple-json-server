#!/usr/bin/env python
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import json
import argparse
import re
import os

LOCALHOST = '127.0.0.1'
DEFAULT_ENCODING = 'utf-8'
PARAM_SPECIFIER = ':'
SEPARATOR = '/'
URL = 'url'
ID = 'id'

# HTTP status codes
OK = 200
BAD_REQUEST = 400
NOT_FOUND = 404
CONFLICT = 409

class HostHandler():
    """
    Class that handles the addition of a host definition to the hosts file.
    This is useful to enable using a different URL than localhost to the mock
    server. Be aware though that, by default, any new host will be mapped to
    localhost, so the way to have multiple mock server instances serving different
    content is by specifying a different port.
    """
    def __init__(self, path_to_hosts=r'C:\Windows\System32\drivers\etc\hosts', address=LOCALHOST, hostname=None):
        self.default_path = path_to_hosts
        self.hostname = hostname
        self.address = address
        self.content = '{}\t{}'.format(self.address, self.hostname)

    def add_host(self, path=None):
        """
        Write the contents of this host definition to the provided path
        """
        if path is None:
            path = self.default_path
        with open(path, 'a') as hosts_file:
            hosts_file.write('\n' + self.content + '\n')

    def remove_host(self, path=None):
        """
        Remove this host from the hosts file
        """
        if path is None:
            path = self.default_path
        content_with_removed_host = []
        remove_next = False
        with open(path, 'r') as hosts_file:
            for line in hosts_file.read().split('\n'):
                if line != self.content and not remove_next:
                    content_with_removed_host += [line]
                else:
                    content_with_removed_host[:-1] # previous line was a blank line
                    remove_next = not remove_next # next line is a blank line
        with open(path, 'w') as hosts_file:
            hosts_file.write('\n'.join(content_with_removed_host))


class SimpleServerHandler(BaseHTTPRequestHandler):
    """
    Class that handles HTTP Requests and Responses. 

    From the documentation of BaseHTTPRequestHandler:

    This server parses the request and the headers, and then calls a
    function specific to the request type (<command>). Specifically,
    a request SPAM will be handled by a method do_SPAM(). If no
    such method exists the server sends an error response to the
    client. If it exists, it is called with no arguments.
    """
    db = None # file from which to write the data
    routes = []
    data = {}
    
    # Methods for internal use
    def _set_headers(self, status_code=OK):
        """
        Set response headers. 
        """
        self.send_response(status_code)
        self.send_header('Content-type', 'text/json')
        self.end_headers()

    def _get_route_and_params(self, route):
        """
        Split a generic route into the path 
        and the parameter. If there is no parameter,
        its value is set to None
        """
        path = None
        param = None
        try:
            path, param = route.split(PARAM_SPECIFIER)
        except:
            path = route
        return path.rstrip(SEPARATOR), param

    def _get_data_key(self, path, param):
        """
        Get the key from which to access a specific set of data
        from the database
        """
        if param is not None:
            return path + SEPARATOR + PARAM_SPECIFIER + param
        return path
        
    def _generate_next_id(self, current_data):
        """
        Generate the next ID from the current list of
        items in the database. Overwrite if a different
        generator is desired. IDs generated here are integers,
        and the returned value is the current max integer 
        in the dataset plus 1.
        """
        return max([e[ID] for e in current_data]) + 1

    def _validate_request(self, param, post_data, current_data):
        """
        Validate the body of a POST request.
        """
        if type(current_data) != list or type(post_data) != dict:
            return CONFLICT
        # there is no parameter, no problem
        if not param or param == ID: 
            return OK
        # There is a parameter
        if not post_data.get(param, ''): # Check if post body contains the parameter
            return BAD_REQUEST
        # There is a parameter and the body contains the parameter
        if post_data.get(param, '') in [i[param] for i in current_data]: # check that the value isn't repeated
            return CONFLICT
        return OK

    def _API_response(self, code):
        """
        Perpare the API response
        """
        resp = [status_code for status_code in HTTPStatus if status_code.value == code]
        if len(resp) == 1:
            resp = resp[0]
            return {
                'result': {
                    'code': resp.value,
                    'message': resp.phrase,
                    'description': resp.description
                }
            }

    # Handle HTTP requests
    def do_GET(self):
        """
        Handle GET requests
        """
        # check if the request path matches any of the endpoints
        for endpoint in self.routes:
            endpoint_path, param = self._get_route_and_params(endpoint)

            # if the endpoint being tested is not part of the request url
            # there's no need for further processing, skip to the next one
            if endpoint_path not in self.path:
                continue

            # if there is no parameter but an endpoint was matched, return all the data
            if self.path.endswith(SEPARATOR + endpoint_path): 
                    self._set_headers()
                    self.wfile.write(bytes(json.dumps(self.data[self._get_data_key(endpoint_path, param)]), DEFAULT_ENCODING))
                    return

            # else a parameter value has been included in the request
            _, param_val = self.path.rsplit(SEPARATOR, 1)

            # try to get value
            data_to_send = [i for i in self.data[self._get_data_key(endpoint_path, param)] if str(i[param]) == str(param_val)]
            if len(data_to_send) == 0:
                continue
            if len(data_to_send) == 1:
                data_to_send = data_to_send[0]

            self._set_headers()
            self.wfile.write(bytes(json.dumps(data_to_send), DEFAULT_ENCODING))
            return

        # Nothing matched the request
        self._set_headers(NOT_FOUND)
        self.wfile.write(bytes(json.dumps(self._API_response(NOT_FOUND)), DEFAULT_ENCODING))
        
    def do_POST(self):
        """
        Handle POST requests
        """
        valid_path = False
        for endpoint in self.routes:

            endpoint_path, param = self._get_route_and_params(endpoint)
            
            if self.path.endswith(SEPARATOR + endpoint_path):
                    valid_path = True
                    status_code = OK
                    # read post data
                    post_data = json.loads(self.rfile.read(int(self.headers.get('Content-Length'))).decode("UTF-8"))

                    try:
                        current_data = self.data[self._get_data_key(endpoint, None)]
                        status_code = self._validate_request(param, post_data, current_data)

                        if status_code != OK:
                            self._set_headers(status_code)
                            self.wfile.write(bytes(json.dumps(self._API_response(status_code)), DEFAULT_ENCODING))
                            return

                        # If valid, add object to list
                        post_data[ID] = self._generate_next_id(current_data)
                        self.data[endpoint] = current_data + [post_data]

                        with open(self.db, 'w') as f:
                            f.write(json.dumps(self.data))
                    except:
                        status_code = BAD_REQUEST

                    self._set_headers(status_code)
                    self.wfile.write(bytes(json.dumps(self._API_response(status_code)), DEFAULT_ENCODING))

        if not valid_path:
            self._set_headers(NOT_FOUND)
            self.wfile.write(bytes(json.dumps(self._API_response(NOT_FOUND)), DEFAULT_ENCODING))

class SimpleServer(HTTPServer):
    """
    Class used to set the data file from 
    which to extract the routing and data
    """
    def __init__(self, server_address, handler_class, dbfile):
        SimpleServerHandler.db = dbfile
        SimpleServerHandler.routes = build_router(dbfile)
        SimpleServerHandler.data = load_data(dbfile)
        super(SimpleServer, self).__init__(server_address, handler_class)


def build_router(dbfile):
    """
    Get the list of supported routes
    """
    # build route handler from datafile
    with open(dbfile, 'r') as f:
        return list(json.load(f).keys())

def load_data(dbfile):
    """
    Get the data from the specified file
    """
    # load data from datafile
    with open(dbfile, 'r') as f:
        return json.load(f)

def run(server_class=SimpleServer, handler_class=SimpleServerHandler, port=80, file='db.json', url=None):
    """
    Run the server forever listening at the specified port
    """
    log_url = url if url else 'localhost'
    log_port = ':{}/'.format(port) if port!=80 else SEPARATOR 
    log_msg = '\nRunning at http://{}{}'.format(log_url, log_port)
    server_address = ('', int(port))
    httpd = server_class(server_address, handler_class, file)

    print('Starting Server...')
    print('Listening to connections on port: ' + str(port))
    print('Routing and data will be extracted from: ' + file)
    print(log_msg)
    
    httpd.serve_forever()

def parse_args():
    """
    Process command line arguments and return them as a dict
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', help='Specify the desired port, defaults to port 80')
    parser.add_argument('-f', '--file', help='File from which to extract routing and data, defaults to db.json')
    parser.add_argument('-u', '--url', help='Set a fake url for the server, defaults to localhost')
    
    return dict({k: v for k, v in vars(parser.parse_args()).items() if v is not None})

if __name__ == "__main__":
    args = parse_args()

    if args.get(URL, ''):
        host = HostHandler(hostname=args.get(URL))
        host.add_host()

    try:
        if args:
            run(**args)
        else:
            run()
    except KeyboardInterrupt:
        # gracefully end program and remove entries from hosts files
        if args.get(URL, ''):
            host.remove_host()
