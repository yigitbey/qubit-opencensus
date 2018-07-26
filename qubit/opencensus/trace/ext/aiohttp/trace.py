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
import aiohttp

from qubit.opencensus.trace import asyncio_context

log = logging.getLogger(__name__)

MODULE_NAME = 'aiohttp'


def trace_integration(tracer=None, propagator=None):
    """Wrap the requests library to trace it."""
    log.info('Integrated module: {}'.format(MODULE_NAME))
    # Wrap the aiohttp functions
    aiohttp_func = getattr(aiohttp.ClientSession, '_request')
    wrapped = wrap_aiohttp(aiohttp_func, propagator=propagator)
    setattr(aiohttp.ClientSession, aiohttp_func.__name__, wrapped)


def wrap_aiohttp(aiohttp_func, propagator=None):
    """Wrap the aiohttp function to trace it."""
    async def call(*args, **kwargs):
            _tracer = asyncio_context.get_opencensus_tracer()
            if _tracer is None:
                return await aiohttp_func(*args, **kwargs)

            _span = _tracer.start_span()
            _span.name = '[aiohttp] {}'.format(args[1])
            _tracer.add_attribute_to_current_span('aiohttp/method', str(args[1]))
            _tracer.add_attribute_to_current_span('aiohttp/url', str(args[2]))

            if propagator is not None:
                span_context = _span.context_tracer.span_context
                headers = propagator.to_headers(span_context)
                if 'headers' not in kwargs:
                    kwargs['headers'] = {}
                for k, v in headers.items():
                    kwargs['headers'][k] = v

            try:
                response = await aiohttp_func(*args, **kwargs)

                _tracer.add_attribute_to_current_span(
                    'aiohttp/status_code', str(response.status))
                _tracer.add_attribute_to_current_span(
                    'aiohttp/status_reason', str(response.reason))

                if response.status >= 500:
                    _tracer.add_attribute_to_current_span(
                        'error', True)

                _tracer.end_span()

                return response
            except Exception as e:
                _tracer.add_attribute_to_current_span(
                    'error', True)
                _tracer.add_attribute_to_current_span(
                    'error.message', str(e))
                _tracer.end_span()
                raise e

    return call
