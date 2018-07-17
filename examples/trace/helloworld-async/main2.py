# This is just here for me to test

from sanic import Sanic
from sanic.exceptions import SanicException, InvalidUsage
from sanic.response import json
from opencensus.trace.exporters import jaeger_exporter
from opencensus.trace.samplers import probability
from qubit.opencensus.trace import asyncio_context
from qubit.opencensus.trace.ext.aiohttp.trace import trace_integration as aiohttp_integration
from qubit.opencensus.trace.ext.aioredis.trace import trace_integration as aioredis_integration
from qubit.opencensus.trace.ext.sanic.sanic_middleware import SanicMiddleware
from qubit.opencensus.trace.propagation import jaeger_format
from qubit.opencensus.trace.tracers import asyncio_context_tracer

import asyncio
import aiotask_context as context
import aiohttp
import aioredis


loop = asyncio.get_event_loop()
loop.set_task_factory(context.task_factory)

sampler = probability.ProbabilitySampler(rate=0.5)
propagator = jaeger_format.JaegerFormatPropagator()
exporter = jaeger_exporter.JaegerExporter(service_name="thing")

aiohttp_integration(propagator=propagator)
aioredis_integration(tracer=None)


app = Sanic()
middleware = SanicMiddleware(
                app, 
                sampler=sampler,
                exporter=exporter,
                propagator=propagator)

@asyncio_context_tracer.span()
async def somefunc():
    return "yay"

@app.route('/')
async def root(req):
   conn = await aioredis.create_connection('redis://localhost', loop=loop)
   tracer = asyncio_context.get_opencensus_tracer()
   with tracer.span(name='span1') as span1:
       with tracer.span(name='span2') as span2:
            async with aiohttp.ClientSession() as session:
                result = await session.get("http://localhost:8080")
                result2 = await session.get("http://localhost:8080")
                return json({"hello": await somefunc()})


def main():
    server = app.create_server(host='0.0.0.0', port=8081)
    loop = asyncio.get_event_loop()
    loop.set_task_factory(context.task_factory)
    task = asyncio.ensure_future(server)
    try:
        loop.run_forever()
    except:
        loop.stop()


if __name__ == '__main__':
    main()
