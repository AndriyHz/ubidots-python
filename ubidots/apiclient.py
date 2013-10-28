import requests
import json

BASE_URL = 'http://app.ubidots.com/api/'


class UbidotsError(Exception):
    """Generic Ubidots error"""


class UbidotsError400(UbidotsError):
    """Exception thrown when server returns status code 400"""


class UbidotsError500(UbidotsError):
    """Exception thrown when server returns status code 500"""


class UbidotsInvalidInputError(UbidotsError):
    """Exception thrown when client-side verification fails"""


def create_exception_object(code, body):
    """Creates an Exception object for an erronous status code."""
    if code == 500:
        return UbidotsError500("An Internal Server Error Occurred.")
    elif code == 400:
        return UbidotsError400("Your request is invalid:\n  " + body)
    else:
        return UbidotsError(body)


def raise_informative_exception(list_of_error_codes):
    def real_decorator(fn):
        def wrapped_f(self, *args, **kwargs):
            response = fn(self, *args, **kwargs)
            if response.status_code in list_of_error_codes:
                try:
                    body = response.text
                except:
                    body = "No body found"

                error = create_exception_object(response.status_code, body)
                raise error
            else:
                return response
        return wrapped_f
    return real_decorator


def try_again(list_of_error_codes, number_of_tries=2):
    def real_decorator(fn):
        def wrapped_f(self, *args, **kwargs):
            for i in range(number_of_tries):
                response = fn(self, *args, **kwargs)
                if response.status_code not in list_of_error_codes:
                    return response
                else:
                    self.initialize()
            return response
        return wrapped_f
    return real_decorator


def validate_input(type, required_keys=[]):
    '''
    Decorator for validating input on the client side.

    Usage:

      @validate_input(dict, ['name'])
      def foo(self, data):
          # We can now assume that data is a dict and has the key 'name':
          bar(data['name'])

     or

      @validate_input(list, ['name'])
      def foo(self, data):
          # We can now assume that data is a list of dicts and has each has the
          # key 'name':
          for elem in data:
              bar(elem['name'])

    Args:
      type           Required type of the first argument
      required_keys  If the first argument is a dict or list, checks for existance
                     of required keys in argument or its elements respectively.
    '''
    def real_decorator(fn):
        def wrapped_f(self, *args, **kwargs):
            if not isinstance(args[0], type):
                raise UbidotsInvalidInputError("Invalid argument type. Required: " + str(type))

            def check_keys(obj):
                for key in required_keys:
                    if key not in obj:
                        raise UbidotsInvalidInputError('Key "%s" is missing' % key)

            if isinstance(args[0], list):
                map(check_keys, args[0])
            elif isinstance(args[0], dict):
                check_keys(args[0])

            return fn(self, *args, **kwargs)
        return wrapped_f
    return real_decorator


class ServerBridge(object):
    '''
    Responsabilites: Make petitions to the browser with the right headers and arguments
    '''

    def __init__(self, apikey):
        self.base_url = BASE_URL
        self._token = None
        self._apikey = apikey
        self._apikey_header = {'X-UBIDOTS-APIKEY': self._apikey}
        self.initialize()


    def _get_token(self):
        self._token = self._post_with_apikey('auth/token').json()['token']
        self._token_header = {'X-AUTH-TOKEN': self._token}

    def initialize(self):
        self._get_token()

    @raise_informative_exception([400, 500, 401, 403])
    def _post_with_apikey(self, path):
        headers = self._prepare_headers(self._apikey_header)
        response = requests.post(self.base_url + path, headers =  headers)
        return response

    @try_again([403, 401])
    @raise_informative_exception([400, 500])
    def get(self, path):
        headers = self._prepare_headers(self._token_header)
        response = requests.get(self.base_url + path, headers = headers)
        return response

    def get_with_url(self, url):
        headers = self._prepare_headers(self._token_header)
        response = requests.get(url, headers = headers)
        return response

    @try_again([403, 401])
    @raise_informative_exception([400, 500])
    def post(self, path, data):
        headers = self._prepare_headers(self._token_header)
        data = self._prepare_data(data)
        response = requests.post(self.base_url + path, data=data, headers = headers)
        return response

    @try_again([403, 401])
    @raise_informative_exception([400, 500])
    def delete(self, path):
        headers = self._prepare_headers(self._token_header)
        response = requests.delete(self.base_url + path, headers = headers)
        return response


    def _prepare_headers(self, *args, **kwargs):
        headers = self._transform_a_list_of_dictionaries_to_a_dictionary(args)
        return dict(headers.items() + self._get_custom_headers().items() + kwargs.items())

    def _prepare_data(self, data):
        return json.dumps(data)

    def _get_custom_headers(self):
        headers = {'content-type': 'application/json'}
        return headers

    def _transform_a_list_of_dictionaries_to_a_dictionary(self, list_of_dicts):
        headers = {}
        for dictionary in list_of_dicts:
            for key,val in dictionary.items():
                headers[key] = val
        return headers

class ApiObject(object):

    def __init__(self, raw_data, api, *args, **kwargs):
        self.raw = raw_data
        self.api = api
        self.bridge = self.api.bridge
        self._from_raw_to_attributes()

    def _from_raw_to_attributes(self):
        for key, value in self.raw.items():
            setattr(self, key, value)

class Datasource(ApiObject):

    def remove_datasource(self):
        response = self.bridge.delete('datasources/'+ self.id).json()
        return response

    def get_variables(self):
        response = self.bridge.get('datasources/'+self.id+'/variables')
        variables = self.api._transform_to_variable_objects(response.json())
        return variables

    @validate_input(dict, ["name", "unit", "icon"])
    def create_variable(self, data):
        response = self.bridge.post('datasources/'+self.id+'/variables', data)
        return Variable(response.json(), self.api, datasource= self)

    def __repr__(self):
        return self.name


class Variable(ApiObject):

    def __init__(self, raw_data, api,  *args, **kwargs):
        super(Variable, self).__init__(raw_data, api, *args, **kwargs)
        self.datasource = self._get_datasource(**kwargs)    

    def get_values(self):
        return self.bridge.get('variables/'+self.id+'/values').json()

    @validate_input(dict, ["value"])
    def save_value(self, data):
        if not isinstance(data.get('timestamp', 0), int):
            raise UbidotsInvalidInputError('Key "timestamp" must point to an int value.')

        return self.bridge.post('variables/'+ self.id +'/values', data).json()

    @validate_input(list, ["key", "timestamp"])
    def save_values(self, data, force=False):
        if not all(isinstance(e['timestamp'], int) for e in data):
            raise UbidotsInvalidInputError('Key "timestamp" must point to an int value')

        path = 'variables/'+ self.id +'/values'
        path += ('', '?force=true')[int(force)]
        return self.bridge.post(path, data).json()

    def remove_variable(self):
        return self.bridge.delete('variables/'+self.id).json()

    def _get_datasource(self, **kwargs):
        datasource = kwargs.get('datasource',None)
        if not datasource:
            datasource = self.api.get_datasource(url = self.datasource['url'])
        return datasource

    def __repr__(self):
        return self.name



class ApiClient(object):
    def __init__(self, apikey):
        self.bridge = ServerBridge(apikey)

    def get_datasources(self):
        raw_datasources = self.bridge.get('datasources').json()
        return self._transform_to_datasource_objects(raw_datasources)

    def get_datasource(self, id=None, url=None):
        if not id and not url:
            raise UbidotsInvalidInputError("id or url required")

        if id:
            if not isinstance(id, basestring):
                raise UbidotsInvalidInputError('Argument "id" must be a string.')

            raw_datasource = self.bridge.get('datasources/'+ str(id) ).json()
        elif url:
            if not isinstance(id, basestring):
                raise UbidotsInvalidInputError('Argument "url" must be a string.')

            raw_datasource = self.bridge.get_with_url(url).json()

        return Datasource(raw_datasource, self)

    @validate_input(dict, ["name"])
    def create_datasource(self, data):
        raw_datasource = self.bridge.post('datasources/', data).json()
        return Datasource(raw_datasource, self)

    def get_variables(self):
        raw_variables = self.bridge.get('variables').json()
        return self.transform_to_variables_objects(raw_variables)

    def get_variable(self, id):
        raw_variable = self.bridge.get('variables/'+ str(id) ).json()
        return Variable(raw_variable, self)

    @validate_input(list, ["variable", "value"])
    def save_collection(self, data, force=False):
        path = "collections/values"
        path += ('', '?force=true')[int(force)]
        return self.bridge.post(path, data).json()

    def _transform_to_datasource_objects(self, raw_datasources):
        datasources = []
        for ds in raw_datasources:
            datasources.append(Datasource(ds, self))
        return datasources

    def _transform_to_variable_objects(self, raw_variables):
        variables = []
        for variable in raw_variables:
            variables.append(Variable(variable, self))
        return variables
