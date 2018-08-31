# Copyright 2017, OpenCensus Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import wrapt

from qubit.opencensus.trace import asyncio_context
from opencensus.trace import span as trace_span
from opencensus.trace.tracers.noop_tracer import NoopTracer

log = logging.getLogger(__name__)

MODULE_NAME = 'aioredis'

CONNECTION_WRAP_METHODS = 'execute'
CONNECTION_CLASS_NAME = 'RedisConnection'


def trace_integration(tracer=None):
    # Wrap Session class
    wrapt.wrap_function_wrapper(
        MODULE_NAME, 'RedisConnection.execute', wrap_execute)


async def wrap_execute(wrapped, instance, args, kwargs):
    """Wrap the session function to trace it."""
    command = args[0]
    _tracer = asyncio_context.get_opencensus_tracer()

    if _tracer is None or isinstance(_tracer, NoopTracer):
        return await wrapped(*args, **kwargs)

    parent_span = _tracer.current_span()
    _span = parent_span.span(name='[aioredis] {}'.format(command))
    _span.add_attribute('redis.db', instance.db)
    _span.add_attribute('redis.address', instance.address[0])
    _span.add_attribute('redis.port', instance.address[1])
    _span.add_attribute('redis.encoding',
            str(instance.encoding))
    if len(args) > 1:
        _span.add_attribute('redis.key', args[1])

    # Add the requests url to attributes
    try:
        _span.start()
        result = await wrapped(*args, **kwargs)
        if isinstance(result, bytes):
            _span.add_attribute('redis.resposne.size',
                    len(result))
        else:
            _span.add_attribute('redis.resposne.size',
                    0)
        return result
    except Exception as e:
        _span.add_attribute('error', True)
        _span.add_attribute('error.message', str(e))
        raise(e)
    finally:
        _span.finish()
