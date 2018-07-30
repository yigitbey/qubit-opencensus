# This is just here for me to test

from sanic import Sanic
from sanic.exceptions import SanicException, InvalidUsage
from sanic.response import json
from qubit.opencensus.trace import asyncio_context
from qubit.opencensus.trace.exporters import jaeger_exporter
from qubit.opencensus.trace.ext.aiohttp.trace import trace_integration as aiohttp_integration
from qubit.opencensus.trace.ext.aioredis.trace import trace_integration as aioredis_integration
from qubit.opencensus.trace.ext.sanic.sanic_middleware import SanicMiddleware
from qubit.opencensus.trace.propagation import jaeger_format
from qubit.opencensus.trace.samplers import probability
from qubit.opencensus.trace.tracers import asyncio_context_tracer

import asyncio
import aiotask_context as context
import aiohttp
import aioredis


sampler = probability.ProbabilitySampler(rate=0.9)
propagator = jaeger_format.JaegerFormatPropagator()
exporter = jaeger_exporter.JaegerExporter(service_name="recs")

aiohttp_integration(propagator=propagator)
aioredis_integration(tracer=None)


app = Sanic()
middleware = SanicMiddleware(
                app, 
                sampler=sampler,
                exporter=exporter,
                propagator=propagator)

@app.listener('before_server_start')
async def init_host(_app, loop):
    _app.conn = await aioredis.create_connection('redis://localhost', loop=loop)
    loop.set_task_factory(context.task_factory)

@asyncio_context_tracer.span()
async def somefunc():
    raise ("boo")
    return "yay"

@app.route('/')
async def root(req):
   tracer = asyncio_context.get_opencensus_tracer()
   with tracer.span(name='span1') as span1:
       with tracer.span(name='span2') as span2:
            async with aiohttp.ClientSession() as session:
                response = await req.app.conn.execute("get", "foobar")
                response = await session.get("https://ifconfig.co")
                return json({"hello": "world"})

@app.route('/yo')
async def thing(req):
    return json({"yo": "lo"})


def main():
    server = app.run(host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
