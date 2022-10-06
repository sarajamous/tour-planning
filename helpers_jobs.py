# Copyright 2022 D-Wave Systems Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import datetime

from dwave.cloud.api import exceptions, Problems
import dimod
from formatting import *

__all__ = ["cancel", "elapsed", "get_status", ]

def cancel(client, job_id):
    """Try to cancel a job submission."""
    p = Problems(endpoint=client.endpoint, token=client.token)
    try:
        status = p.cancel_problem(job_id)
        return status
    except Exception as err:
        return err

def elapsed(ref_time):
    """Return elapsed time in seconds."""
    return (datetime.datetime.now() -
        datetime.datetime.strptime(ref_time, "%c")).seconds

def get_status(client, job_id, job_submit_time):
    """Return elapsed time in seconds."""
    p = Problems(endpoint=client.endpoint, token=client.token)
    try:
        status = p.get_problem_status(job_id)
        label_time = dict(status)["label"].split("submitted: ")[1]
        if label_time == job_submit_time:
            return status.status.value
        else:
            return None
    except exceptions.ResourceNotFoundError as err:
        return None
