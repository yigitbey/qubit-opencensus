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

import inspect
import logging

from sanic.exceptions import SanicException

from opencensus.trace import attributes_helper
from opencensus.trace.exporters import print_exporter
from opencensus.trace.exporters.transports import sync
from opencensus.trace.ext import utils
from opencensus.trace.samplers import always_on, probability
from opencensus.trace.tracers import (
    noop_tracer as noop_tracer_module
)
from qubit.opencensus.trace import asyncio_context
from qubit.opencensus.trace.propagation import jaeger_format
from qubit.opencensus.trace.tracers import (
    asyncio_context_tracer as tracer_module,
)


BLACKLIST_PATHS = 'BLACKLIST_PATHS'
SAMPLING_RATE = 'SAMPLING_RATE'

log = logging.getLogger(__name__)


class SanicMiddleware(object):
    DEFAULT_SAMPLER = always_on.AlwaysOnSampler
    DEFAULT_EXPORTER = print_exporter.PrintExporter
    DEFAULT_PROPAGATOR = jaeger_format.JaegerFormatPropagator

    """sanic middleware to automatically trace requests.

    :type app: :class: `~sanic.sanic`
    :param app: A sanic application.

    :type blacklist_paths: list
    :param blacklist_paths: Paths that do not trace.

    :type sampler: :class: `type`
    :param sampler: Class for creating new Sampler objects. It should extend
                    from the base :class:`.Sampler` type and implement
                    :meth:`.Sampler.should_sample`. Defaults to
                    :class:`.AlwaysOnSampler`. The rest options are
                    :class:`.AlwaysOffSampler`, :class:`.FixedRateSampler`.

    :type exporter: :class: `type`
    :param exporter: Class for creating new exporter objects. Default to
                     :class:`.PrintExporter`. The rest option is
                     :class:`.FileExporter`.

    :type propagator: :class: 'type'
    :param propagator: Class for creating new propagator objects. Default to
                       :class:`.GoogleCloudFormatPropagator`. The rest option
                       are :class:`.BinaryFormatPropagator`,
                       :class:`.TextFormatPropagator` and
                       :class:`.TraceContextPropagator`.
    """
    def __init__(self, app=None, blacklist_paths=None, sampler=None,
                 exporter=None, propagator=None):
        self.app = app
        self.blacklist_paths = blacklist_paths
        self.sampler = sampler
        self.exporter = exporter
        self.propagator = propagator

        if self.app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app

        # get settings from app config
        settings = self.app.config.get('OPENCENSUS_TRACE', {})

        self.sampler = (self.sampler
                        or settings.get('SAMPLER',
                                        self.DEFAULT_SAMPLER))
        self.exporter = (self.exporter
                         or settings.get('EXPORTER',
                                         self.DEFAULT_EXPORTER))
        self.propagator = (self.propagator
                           or settings.get('PROPAGATOR',
                                           self.DEFAULT_PROPAGATOR))

        # get params from app config
        params = self.app.config.get('OPENCENSUS_TRACE_PARAMS', {})

        self.blacklist_paths = params.get(BLACKLIST_PATHS,
                                          self.blacklist_paths)

        # Initialize the sampler
        if not inspect.isclass(self.sampler):
            pass  # handling of instantiated sampler
        elif self.sampler.__name__ == 'ProbabilitySampler':
            _rate = params.get(SAMPLING_RATE,
                               probability.DEFAULT_SAMPLING_RATE)
            self.sampler = self.sampler(_rate)
        else:
            self.sampler = self.sampler()

        transport = sync.SyncTransport

        # Initialize the exporter
        if not inspect.isclass(self.exporter):
            pass  # handling of instantiated exporter
        else:
            self.exporter = self.exporter(transport=transport)

        # Initialize the propagator
        if inspect.isclass(self.propagator):
            self.propagator = self.propagator()

        @app.middleware('request')
        async def trace_request(request):
            self.do_trace_request(request)

        @app.middleware('response')
        async def trace_response(request, response):
            self.do_trace_response(request, response)

    def do_trace_request(self, request):
        if utils.disable_tracing_url(request.url, self.blacklist_paths):
            return

        span_context = self.propagator.from_headers(request.headers)

        tracer = noop_tracer_module.NoopTracer()
        if span_context.from_header and span_context.trace_options.enabled:
            tracer = tracer_module.ContextTracer(
                span_context=span_context,
                exporter=self.exporter)
        elif self.sampler.should_sample(span_context.trace_id):
            tracer = tracer_module.ContextTracer(
                exporter=self.exporter)

        span = tracer.start_span()

        route = request.app.router.get(request)
        # Set the span name as the name of the current module name
        span.name = '[sanic] {} {}'.format(
            request.method,
            route[3])
        tracer.add_attribute_to_current_span(
            'http.nethod', request.method)
        tracer.add_attribute_to_current_span(
            'http.host', request.host)
        tracer.add_attribute_to_current_span(
            'http.scheme', request.scheme)
        tracer.add_attribute_to_current_span('http.url', request.url)
        tracer.add_attribute_to_current_span(
            'http.client.ip', request.ip)

        for header in ['user-agent','x-forwarded-for','x-real-ip']:
            if header in request.headers:
                tracer.add_attribute_to_current_span(
                    'http.headers.'+header, request.headers[header])

        request['tracer'] = tracer

        asyncio_context.set_opencensus_tracer(tracer)

    def do_trace_response(self, request, response):
        """A function to be run after each request.
        """
        # Do not trace if the url is blacklisted
        if utils.disable_tracing_url(request.url, self.blacklist_paths):
            return
        if 'tracer' not in request:
            return

        tracer = request['tracer']
        tracer.add_attribute_to_current_span(
            'http.status_code',
            str(response.status))
        if response.status >= 500:
            tracer.add_attribute_to_current_span('error', True)

        tracer.end_span()
        tracer.finish()
