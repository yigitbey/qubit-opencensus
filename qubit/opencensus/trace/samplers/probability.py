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

from opencensus.trace.samplers.base import Sampler

DEFAULT_SAMPLING_RATE = 0.5

MAX_VALUE = 0xffffffffffffffff


class ProbabilitySampler(Sampler):
    """Sample a request at a fixed rate.
    Our internal spans often end up being 64 bit (rather than 128 assumed by
    OpenCensus). We'll fix this, but until then, we need to sample based on the
    first 64 bits. not the last.


    :type rate: float
    :param rate: The rate of sampling.
    """
    def __init__(self, rate=None):
        if rate is None:
            rate = DEFAULT_SAMPLING_RATE

        if rate > 1 or rate < 0:
            raise ValueError('Rate must between 0 and 1.')

        self.rate = rate

    def should_sample(self, trace_id):
        """Make the sampling decision based on the upper 8 bytes of the trace
        ID. If the value is less than the bound, return True, else False.

        :type trace_id: str
        :param trace_id: Trace ID of the current trace.

        :rtype: bool
        :returns: The sampling decision.
        """
        upper_long = get_upper_long_from_trace_id(trace_id)
        bound = self.rate * MAX_VALUE

        if upper_long <= bound:
            return True
        else:
            return False


def get_upper_long_from_trace_id(trace_id):
    """Returns the upper 8 bytes of the trace ID as a long value, assuming
    little endian order.

    :rtype: long
    :returns: Upper 8 bytes of trace ID
    """
    upper_bytes = trace_id[:16]
    upper_long = int(upper_bytes, 16)

    return upper_long
