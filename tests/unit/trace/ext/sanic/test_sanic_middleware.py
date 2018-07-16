#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import pytest
import unittest

import asyncio

import aiotask_context as context

import sanic
from sanic.exceptions import SanicException
from sanic.response import json
import mock

from opencensus.trace import span_data
from opencensus.trace import stack_trace
from opencensus.trace import status
from opencensus.trace.exporters import print_exporter, jaeger_exporter
from opencensus.trace.samplers import always_off, always_on, ProbabilitySampler
from opencensus.trace.tracers import base
from opencensus.trace.tracers import noop_tracer
from qubit.opencensus.trace import asyncio_context
from qubit.opencensus.trace.ext.sanic import sanic_middleware
from qubit.opencensus.trace.propagation import jaeger_format


@pytest.yield_fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    loop.set_task_factory(context.task_factory)
    yield loop
    loop.close()


class TestSanicMiddleware(unittest.TestCase):
    @staticmethod
    def create_app():
        app = sanic.Sanic(__name__)

        @app.route('/')
        def index(request):
            return json('test sanic trace')  # pragma: NO COVER

        @app.route('/_ah/health')
        def health_check(request):
            return json('test health check')  # pragma: NO COVER

        @app.route('/error')
        def error(request):
            raise Exception('error')

        return app


    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_constructor_default(self):
        app = mock.Mock(config={})
        middleware = sanic_middleware.SanicMiddleware(app=app)

        self.assertIs(app, middleware.app)
        self.assertTrue(app.do_trace_request.called)
        self.assertTrue(app.do_trace_response.called)
        assert isinstance(middleware.sampler, always_on.AlwaysOnSampler)
        assert isinstance(middleware.exporter, print_exporter.PrintExporter)
        assert isinstance(
            middleware.propagator,
            jaeger_format.JaegerFormatPropagator)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_constructor_explicit(self):
        app = mock.Mock(config={})
        sampler = mock.Mock()
        exporter = mock.Mock()
        propagator = mock.Mock()

        middleware = sanic_middleware.SanicMiddleware(
            app=app,
            sampler=sampler,
            exporter=exporter,
            propagator=propagator)

        self.assertIs(middleware.app, app)
        self.assertIs(middleware.sampler, sampler)
        self.assertIs(middleware.exporter, exporter)
        self.assertIs(middleware.propagator, propagator)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_init_app(self):
        app = mock.Mock()

        middleware = sanic_middleware.SanicMiddleware()
        middleware.init_app(app)

        self.assertIs(middleware.app, app)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_init_app_config_jaeger_exporter(self):
        app = mock.Mock()
        app.config = {
            'OPENCENSUS_TRACE': {
                'SAMPLER': ProbabilitySampler,
                'EXPORTER': jaeger_exporter.JaegerExporter,
                'PROPAGATOR': jaeger_format.JaegerFormatPropagator,
            },
            'OPENCENSUS_TRACE_PARAMS': {
                'BLACKLIST_PATHS': ['/_ah/health'],
                'GCP_EXPORTER_PROJECT': None,
                'SAMPLING_RATE': 0.5,
                'ZIPKIN_EXPORTER_SERVICE_NAME': 'my_service',
                'ZIPKIN_EXPORTER_HOST_NAME': 'localhost',
                'ZIPKIN_EXPORTER_PORT': 9411,
            },
        }

        class JaegerExporter(object):
            def __init__(self, *args, **kwargs):
                pass

        middleware = sanic_middleware.SanicMiddleware(
            exporter=JaegerExporter
        )
        middleware.init_app(app)

        self.assertIs(middleware.app, app)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_init_app_config_zipkin_exporter(self):
        app = mock.Mock()
        app.config = {
            'OPENCENSUS_TRACE': {
                'SAMPLER': ProbabilitySampler,
                'EXPORTER': zipkin_exporter.ZipkinExporter,
                'PROPAGATOR': jaeger_format.JaegerFormatPropagator,
            },
            'OPENCENSUS_TRACE_PARAMS': {
                'ZIPKIN_EXPORTER_SERVICE_NAME': 'my_service',
                'ZIPKIN_EXPORTER_HOST_NAME': 'localhost',
                'ZIPKIN_EXPORTER_PORT': 9411,
            },
        }

        middleware = sanic_middleware.SanicMiddleware()
        middleware.init_app(app)

        self.assertIs(middleware.app, app)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test__do_trace_request(self):
        from qubit.opencensus.trace import asyncio_context

        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = '2dd43a1d6b2549c6bc2a1a54c2fc0b05'
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)

        app = mock.Mock(config={})
        sanic_middleware.SanicMiddleware(app=app)
        context = app.test_request_context(
            path='/',
            headers={sanic_trace_header: sanic_trace_id})

        with context:
            app.preprocess_request()
            tracer = asyncio_context.get_opencensus_tracer()
            self.assertIsNotNone(tracer)

            span = tracer.current_span()

            expected_attributes = {
                '/http/url': u'http://localhost/',
                '/http/method': 'GET',
            }

            self.assertEqual(span.attributes, expected_attributes)
            self.assertEqual(span.parent_span.span_id, span_id)

            span_context = tracer.span_context
            self.assertEqual(span_context.trace_id, trace_id)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test__before_request_blacklist(self):
        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = '2dd43a1d6b2549c6bc2a1a54c2fc0b05'
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)

        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app)
        context = app.test_request_context(
            path='/_ah/health',
            headers={sanic_trace_header: sanic_trace_id})

        with context:
            app.preprocess_request()
            tracer = asyncio_context.get_opencensus_tracer()
            assert isinstance(tracer, noop_tracer.NoopTracer)

            span = tracer.current_span()

            assert isinstance(span, base.NullContextManager)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_header_encoding(self):
        # The test is for detecting the encoding compatibility issue in
        # Python2 and Python3 and what sanic does for encoding the headers.
        # This test case is expected to fail at the check_trace_id method
        # in SpanContext because it cannot match the pattern for trace_id,
        # And a new trace_id will generate for the context.

        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = "你好"
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)

        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app)
        context = app.test_request_context(
            path='/',
            headers={sanic_trace_header: sanic_trace_id})

        with context:
            app.preprocess_request()
            tracer = asyncio_context.get_opencensus_tracer()
            self.assertIsNotNone(tracer)

            span = tracer.current_span()

            expected_attributes = {
                '/http/url': u'http://localhost/',
                '/http/method': 'GET',
            }

            self.assertEqual(span.attributes, expected_attributes)
            assert isinstance(span.parent_span, base.NullContextManager)

            span_context = tracer.span_context
            self.assertNotEqual(span_context.trace_id, trace_id)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_header_is_none(self):
        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app)
        context = app.test_request_context(
            path='/')

        with context:
            app.preprocess_request()
            tracer = asyncio_context.get_opencensus_tracer()
            self.assertIsNotNone(tracer)

            span = tracer.current_span()

            expected_attributes = {
                '/http/url': u'http://localhost/',
                '/http/method': 'GET',
            }

            self.assertEqual(span.attributes, expected_attributes)
            assert isinstance(span.parent_span, base.NullContextManager)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test__after_request_not_sampled(self):
        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = '2dd43a1d6b2549c6bc2a1a54c2fc0b05'
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)
        sampler = always_off.AlwaysOffSampler()

        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app, sampler=sampler)

        request, response = app.test_client.get(
            '/',
            headers={sanic_trace_header: sanic_trace_id})

        self.assertEqual(response.status, 200)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test__after_request_sampled(self):
        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = '2dd43a1d6b2549c6bc2a1a54c2fc0b05'
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)

        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app)

        request, response = app.test_client.get(
            '/',
            headers={sanic_trace_header: sanic_trace_id})

        self.assertEqual(response.status, 200)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test__after_request_blacklist(self):
        sanic_trace_header = 'X_CLOUD_TRACE_CONTEXT'
        trace_id = '2dd43a1d6b2549c6bc2a1a54c2fc0b05'
        span_id = '6e0c63257de34c92'
        sanic_trace_id = '{}/{}'.format(trace_id, span_id)

        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app)

        request, response = app.test_client.get(
            '/_ah/health',
            headers={sanic_trace_header: sanic_trace_id})

        tracer = asyncio_context.get_opencensus_tracer()

        self.assertEqual(response.status, 200)
        assert isinstance(tracer, noop_tracer.NoopTracer)

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_teardown_include_exception(self):
        mock_exporter = mock.MagicMock()
        app = self.create_app()
        sanic_middleware.SanicMiddleware(app=app, exporter=mock_exporter)
        request, response = app.test_client.get('/error')

        self.assertEqual(response.status, 500)

        exported_spandata = mock_exporter.export.call_args[0][0][0]
        self.assertIsInstance(exported_spandata, span_data.SpanData)
        self.assertIsInstance(exported_spandata.status, status.Status)
        self.assertEqual(exported_spandata.status.message, 'error')

    @pytest.mark.asyncio
    @asyncio.coroutine
    def test_teardown_include_exception_and_traceback(self):
        mock_exporter = mock.MagicMock()
        app = self.create_app()
        app.config['TESTING'] = True
        sanic_middleware.SanicMiddleware(app=app, exporter=mock_exporter)
        app.test_client.get('/error')

        exported_spandata = mock_exporter.export.call_args[0][0][0]
        self.assertIsInstance(exported_spandata, span_data.SpanData)
        self.assertIsInstance(exported_spandata.status, status.Status)
        self.assertEqual(exported_spandata.status.message, 'error')
        self.assertIsInstance(
            exported_spandata.stack_trace, stack_trace.StackTrace
        )
        self.assertIsNotNone(exported_spandata.stack_trace.stack_trace_hash_id)
        self.assertNotEqual(exported_spandata.stack_trace.stack_frames, [])
