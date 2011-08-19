#License#
#bitHopper by Colin Rice is licensed under a Creative Commons 
# Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#Based on a work at github.com.

import json
import base64

import evenlet
httplib2 = eventlet.import_patched('httplib2')

from zope.interface import implements

from client import Agent
from twisted.web.iweb import IBodyProducer
from twisted.web.http_headers import Headers
from twisted.internet import defer
from twisted.internet.defer import succeed, Deferred
from twisted.internet.protocol import Protocol
import twisted.web.client

class StringProducer(object):
    implements(IBodyProducer)

    def __init__(self, body):
        self.body = body
        self.length = len(body)

    def startProducing(self, consumer):
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass

class WorkProtocol(Protocol):

    def __init__(self, finished):
        self.data = ""
        self.finished = finished
    
    def dataReceived(self, data):
        self.data += data

    def connectionLost(self, reason):
        self.finished.callback(self.data)

class Work():
    def __init__(self, bitHopper):
        self.bitHopper = bitHopper
        self.i = 0
        self.httppool = pools.Pool()
        self.httppool.create = httplib2.Http()

    def jsonrpc_lpcall(self, server, url, lp):
        try:
            self.i += 1
            request = json.dumps({'method':'getwork', 'params':[], 'id':self.i}, ensure_ascii = True)            
            pool = self.bitHopper.pool.servers[server]
            header = {'Authorization':["Basic " +base64.b64encode(pool['user']+ ":" + pool['pass'])], 'User-Agent': ['poclbm/20110709'], 'Content-Type': ['application/json'] }
            resp, content = self.httppool.request( url, 'GET', headers=header, body=request)
            lp.receive(content, server)
            return None
        except Exception, e:
            self.bitHopper.log_dbg('Error in lpcall work.py')
            self.bitHopper.log_dbg(e)
            lp.receive(None, server)
            return None

    def get(self, url):
        "A utility method for getting webpages"
        header = {'User-Agent':['Mozilla/5.0 (Windows; U; MSIE 9.0; WIndows NT 9.0; en-US))']}
        resp, content = self.httppool.request( url, 'GET', headers=header)
        return content

    def jsonrpc_call(self, server, data):
        try:
            request = json.dumps({'method':'getwork', 'params':data, 'id':self.i}, ensure_ascii = True)
            self.i += 1
            
            info = self.bitHopper.pool.servers[server]
            header = {'Authorization':["Basic " +base64.b64encode(info['user']+ ":" + info['pass'])], 'User-Agent': ['poclbm/20110709'],'Content-Type': ['application/json'] }
            url = "http://" + info['mine_address']
            resp, content = self.httppool.request( url, 'POST', headers=header, body=request)
            #Check for long polling header
            lp = self.bitHopper.lp
            if lp.check_lp(server):
                #bitHopper.log_msg('Inside LP check')
                for k,v in rep:
                    if k.lower() == 'x-long-polling':
                        lp.set_lp(v[0],server)
                        break
        except Exception, e:
            self.bitHopper.log_dbg('Caught, jsonrpc_call insides')
            self.bitHopper.log_dbg(server)
            self.bitHopper.log_dbg(e)
            #traceback.print_exc
            return None

        try:
            message = json.loads(content)
            value =  message['result']
            return value
        except Exception, e:
            self.bitHopper.log_dbg( "Error in json decoding, Server probably down")
            self.bitHopper.log_dbg(server)
            self.bitHopper.log_dbg(body)
            return None

    def jsonrpc_getwork(self, server, data, request):
        tries = 0
        work = None
        while work == None:
            tries += 1
            try:
                if tries > 4:
                    eventlet.sleep(0.5)
                work = self.jsonrpc_call(server,data)
            except Exception, e:
                self.bitHopper.log_dbg( 'caught, inner jsonrpc_call loop')
                self.bitHopper.log_dbg(server)
                self.bitHopper.log_dbg(str(e))
                work = None
            if data == [] and tries > 2:
                server = self.bitHopper.get_new_server(server)
            elif tries > 2:
                self.bitHopper.get_new_server(server)
        defer.returnValue(work)

    @defer.inlineCallbacks
    def handle(self, env, start_request):
        
        start_request( '200 OK', [("Content-type", "text/json"),
                                  ('X-Long-Polling', '/LP')]

        print dir(env['wsgi.input'])
        rpc_request = json.loads(env['wsgi.input'].readall())

        #check if they are sending a valid message
        if rpc_request['method'] != "getwork":
            return

        data = rpc_request['params']
        j_id = rpc_request['id']

        if data != []:
            server = self.bitHopper.getwork_store.get_server(data[0][72:136])
        if data == [] or server == None:
            server = self.bitHopper.pool.get_current()

        work = self.jsonrpc_getwork(server, data, request)

        response = json.dumps({"result":work, 'error':None, 'id':j_id})        
        request.write(response)
        
        #Check if the request has been closed
        if self.bitHopper.request_store.closed(request):
            return
        request.finish()

        #some reject callbacks and merkle root stores
        if str(work) == 'False':
            self.bitHopper.reject_callback(server, data, request.getUser(), request.getPassword())
        elif str(work) != 'True':
            merkle_root = work["data"][72:136]
            self.bitHopper.getwork_store.add(server,merkle_root)

        #Fancy display methods
        if self.bitHopper.options.debug:
            self.bitHopper.log_msg('RPC request ' + str(data) + " submitted to " + server)
        elif data == []:
            self.bitHopper.log_msg('RPC request [' + rpc_request['method'] + "] submitted to " + server)
        else:
            self.bitHopper.log_msg('RPC request [' + str(data[0][155:163]) + "] submitted to " + server)

        if data != []:
            self.bitHopper.data_callback(server, data, request.getUser(), request.getPassword())  
