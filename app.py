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

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State
import json
import plotly.express as px
import pandas as pd
import random
import numpy as np
from pprint import pprint
import time, datetime

from helpers import *
from formatting import *
from tour_planning import init_cqm, init_tour, init_legs
from tour_planning import build_cqm, set_legs, transport
from tool_tips import tool_tips

import dimod
from dwave.cloud.hybrid import Client
from dwave.cloud.api import Problems

modes = transport.keys()  # global, but not user modified
num_modes = len(modes)

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

try:
    client = Client.from_config(profile="test")
except Exception as client_err:
    client = None

job_bar = {'READY': [0, 'link'],
           'WAITING': [0, 'light'],
           'SUBMITTED': [25, 'info'],
           'PENDING': [50, 'warning'],
           'IN_PROGRESS': [75 ,'primary'],
           'COMPLETED': [100, 'success'],
           'CANCELLED': [100, 'dark'],
           'FAILED': [100, 'danger'], }

TERMINATED = ["COMPLETED", "CANCELLED", "FAILED"]
RUNNING = ["PENDING", "IN_PROGRESS"]

# Helper functions
##################

def _dcc_input(name, config_vals, step=None):
    """Sets input to dash.Input elements in layout."""
    suffix = ""
    if "_slider" in name:
        suffix = "_slider"
        name = name.replace("_slider", "")
    return dcc.Input(
        id=f"{name}{suffix}",
        type="number",
        min=config_vals[name][0],
        max=config_vals[name][1],
        step=step,
        value=config_vals[name][2])

def _dcc_slider(name, config_vals, step=1, discrete_slider=False):
    """Sets input to dash.Input elements in layout."""
    suffix = ""
    if "_slider" in name:
        suffix = "_slider"
        name = name.replace("_slider", "")
    if not discrete_slider:
        marks={config_vals[f"{name}"][0]:
            {"label": "Soft", "style": {"color": 'white'}},
            config_vals[f"{name}"][1]:
            {"label": "Hard", "style": {"color": 'white'}}}
    else:
        marks={i: {"label": f'{str(i)}', "style": {"color": "white"}} for i in
        range(config_vals[name][0], init_tour[name][1] + 1, 2*step)}

    return dcc.Slider(
        id=f"{name}{suffix}",
        min=config_vals[f"{name}"][0],
        max=config_vals[f"{name}"][1],
        marks=marks,
        step=step,
        value=config_vals[f"{name}"][2],)

# Problem-submission section
############################

solver_card = dbc.Card([
    html.H4("Job Submission", className="card-title"),
    dbc.Col([
        dbc.Button("Solve CQM", id="btn_solve_cqm", color="primary", className="me-1"),
        dcc.Interval(id="wd_job", interval=None, n_intervals=0, disabled=True, max_intervals=1),
        dbc.Progress(id="bar_job_status", value=0, color="info", className="mb-3"),
        html.P(id="job_submit_state", children=out_job_submit_state("READY")),   # if no client change ready
        html.P(id="job_submit_time", children="", style = dict(display="none")),
        html.P(id="job_sm", children="ready", style = dict(display="none")),
        html.P(id="job_id", children="", style = dict(display="none")),
        html.P(id="job_elapsed_time", children=""),
        dbc.Button("Cancel Job", id="btn_cancel", color="warning", className="me-1",
            style = dict(display="none")),]),],
    color="secondary")

# Tab-construction section
##########################
tabs = {}

graphs = {          # also used for display callback
    "Space": "Displays your configured tour, with leg distance as " + \
        "relative length and elevation by color. Will display best found mode of transport.",
    "Time": "Will display best found solution, with leg duration as relative length.",
    "Diversity": "Will display all returned solutions to submitted problems."}
tabs["Graph"] = dbc.Tabs([
    dbc.Tab(dbc.Card([
        dbc.Row([
            dbc.Col([
                html.P(id=f"{key}_intro", children=val, style={"color": "black"}),
                dcc.Graph(id=f"{key.lower()}_graph")], width=12) ])]),
        label=f"{key}",
        tab_id=f"graph_{key.lower()}",
        label_style={"color": "white", "backgroundColor": "black"},)
    for key, val in graphs.items()])

double_tabs = {    # also used for display callback
    "Problem": "Displays the configured tour: length of each leg, elevation, and "\
        "toll positions.",
    "Solutions": "Displays returned solutions to submitted problems."}
readers = ["Human", "Code"]
viewer_tabs = {}
for key, val in double_tabs.items():
    tabs[key] = dbc.Tabs([
        dbc.Tab(dbc.Card([
            dbc.Row([
                dbc.Col([
                    dcc.Textarea(id=f"{key.lower()}_print_{reader.lower()}", value=val,
                        style={"width": "100%"}, rows=20)])]),]),
            label=f"{reader} Readable",
            tab_id=f"tab_{key}_print_{reader.lower()}",
            label_style={"color": "white", "backgroundColor": "black"},)
    for reader in readers])

single_tabs = {   # also used for display callback
    "CQM": "",
    "Input": "",
    "Transport": out_transport_human(transport)}
for key, val in single_tabs.items():
    tabs[key] = dbc.Card([
        dbc.Row([
            dbc.Col([
                dcc.Textarea(id=f"{key.lower()}_print", value=val,
                    style={"width": "100%"}, rows=20)],)]),])

# Configuration sections
########################

constraint_inputs = {f"weight_{constraint.lower()}": f"{constraint}" for
    constraint in ["Cost", "Time", "Slope"]}      # also used for display callback
constraint_card = [html.H4("CQM Settings", className="card-title")]
constraint_card.extend([
    html.Div([
        dbc.Label(f"{val} Weight"),
        html.Div([
            _dcc_input(key, init_cqm, step=1)],
                style=dict(display="flex", justifyContent="right")),
            _dcc_slider(f"{key}_slider", init_cqm),])
for key, val in constraint_inputs.items()])

tour_titles = ["Set Legs", "Set Budget"]
leg_inputs = {      # also used for callbacks
    "num_legs": "How Many:",
    "max_leg_length": "Longest Leg:",
    "min_leg_length": "Shortest Leg:",
    "max_leg_slope": "Steepest Leg:",}
cqm_inputs = {      # also used for callbacks
    "max_cost": "Highest Cost:",
    "max_time": "Longest Time:"}
leg_rows_inputs = {**leg_inputs, **cqm_inputs}

leg_rows = [dbc.Row([
    f"{val}",
    dash.html.Br(),
    _dcc_input(key, init_tour, step=1) if key != "max_leg_slope" else
    _dcc_slider(key, init_tour, step=1, discrete_slider=True)])
    for key, val in leg_rows_inputs.items()]
tour_config = dbc.Card(
    [dbc.Row([
        html.H4("Tour Settings", className="card-title", style={"textAlign": "left"})]),
     dbc.Row([
        dbc.Col([
            html.B(f"{tour_title}", style={"text-decoration": "underline"},) ])
                for tour_title in tour_titles]),
     dbc.Row([
        dbc.Col(leg_rows[:4], style={"margin-right": "20px"}),
        dbc.Col(leg_rows[4:], style={"margin-left": "20px"}),],)],
    body=True, color="secondary")

# Page-layout section
#####################

layout = [
    dbc.Row([
        dbc.Col([
            html.H1("Tour Planner", style={'textAlign': 'left'})], width=10),
        dbc.Col([
            html.Img(src="assets/ocean.png", height="50px",
                style={'textAlign': 'right'})], width=2)]),
    dbc.Row([
        dbc.Col(
            tour_config, width=4),
        dbc.Col(
            dbc.Card(constraint_card, body=True, color="secondary"),
            width=2),
        dbc.Col([
            dbc.Row([
                dbc.Col([
                    solver_card])]),],
            width=2)],
        justify="left"),
    dbc.Tabs([
        dbc.Tab(
            tabs[tab], label=tab, tab_id=f"tab_{tab.lower()}",
            label_style={"color": "rgb(6, 236, 220)", "backgroundColor": "black"},)
        for tab in tabs.keys()],
        id="tabs", active_tab="tab_graph")]

tips = [dbc.Tooltip(
            message, target=target)
            for target, message in tool_tips.items()]
layout.extend(tips)

app.layout = dbc.Container(
    layout, fluid=True,
    style={"backgroundColor": "black", "color": "rgb(6, 236, 220)"})

# Callbacks Section
###################

@app.callback(
    [Output("input_print", "value")],
    [Output(id, "value") for id in leg_inputs.keys()],
    [Output(id, "value") for id in constraint_inputs.keys()],
    [Output(f"{id}_slider", "value") for id in constraint_inputs.keys()],
    [Input(id, "value") for id in leg_inputs.keys()],
    [Input(id, "value") for id in constraint_inputs.keys()],
    [Input(f"{id}_slider", "value") for id in constraint_inputs.keys()],
    [Input(id, "value") for id in cqm_inputs.keys()],)
def user_inputs(num_legs, max_leg_length, min_leg_length, max_leg_slope, \
    weight_cost, weight_time, weight_slope, \
    weight_cost_slider,  weight_time_slider, weight_slope_slider, \
    max_cost, max_time):
    """
    Handle configurable user inputs.
    Generates input_print readable text.
    """
    trigger = dash.callback_context.triggered
    trigger_id = trigger[0]["prop_id"].split(".")[0]

    if trigger_id == 'max_leg_length' and max_leg_length <= min_leg_length:
        min_leg_length = max_leg_length
    if trigger_id == 'min_leg_length' and min_leg_length >= max_leg_length:
        max_leg_length = min_leg_length

    weights = ["cost", "time", "slope"]
    weight_vals = {}
    for weight in weights:
        weight_vals[weight] = dash.no_update
        if trigger_id == f'weight_{weight}_slider':
            weight_vals[weight] = eval(f'weight_{weight}_slider')
        if trigger_id == f'weight_{weight}':
            weight_vals[weight] = eval(f'weight_{weight}')

    inputs = {**init_tour, **init_cqm}
    for key in inputs.keys():
        inputs[key][2] = eval(key)

    if trigger_id not in {**init_tour, **init_cqm}.keys():
        trigger_id = None

    return out_input_human(inputs, trigger_id),  \
        num_legs, max_leg_length, min_leg_length, max_leg_slope, \
        weight_vals["cost"], weight_vals["time"], weight_vals["slope"], \
        weight_vals["cost"], weight_vals["time"], weight_vals["slope"]

@app.callback(
    [Output("problem_print_code", "value")],
    [Output("problem_print_human", "value")],
    [Input("input_print", "value")],
    [State(id, "value") for id in leg_inputs.keys()])
def legs(input_print, \
    num_legs, max_leg_length, min_leg_length, max_leg_slope):
    """
    Sets the tour legs.
    Generates problem_print code & readable text.
    """
    trigger = dash.callback_context.triggered
    trigger_id = trigger[0]["prop_id"].split(".")[0]

    if trigger_id == "input_print":
        find_changed = [line for line in input_print.split("\n") if "<<--" in line]
        if not find_changed:  # Print initial configuration
            legs = init_legs["legs"]
            return out_problem_code(legs), out_problem_human(legs)
        if find_changed and find_changed[0].split(" ")[0] in leg_inputs.keys():
            legs = set_legs(num_legs, [min_leg_length, max_leg_length], max_leg_slope)
            return out_problem_code(legs), out_problem_human(legs)
        else:
            return dash.no_update, dash.no_update

@app.callback(
    Output("cqm_print", "value"),
    [Input("input_print", "value")],
    [Input("problem_print_code", "value")],
    [State("max_leg_slope", "value")],
    [State(id, "value") for id in constraint_inputs.keys()],
    [State(id, "value") for id in cqm_inputs.keys()])
def cqm(input_print, problem_print_code, max_leg_slope, \
    max_cost, max_time,
    weight_cost, weight_time, weight_slope):
    """
    Create the constrained quadratic model for the tour.
    Generates problem_print code & readable text.
    """

    trigger = dash.callback_context.triggered
    trigger_id = trigger[0]["prop_id"].split(".")[0]

    if trigger_id in ["input_print", "problem_print_code"]:
        try:    # Initial firing of input_print will create the intial problem_print_code
            legs = in_problem_code(problem_print_code)
            cqm = build_cqm(legs, modes, max_leg_slope, max_cost, max_time, \
                weight_cost, weight_time, weight_slope)
            return cqm.__str__()
        except ValueError:  # Initial pass won't load JSON
            return dash.no_update

@app.callback(
    [Output(f'{key.lower()}_graph', 'figure') for key in graphs.keys()],
    Input("solutions_print_code", "value"),
    Input("problem_print_code", "value"))
def graphics(solutions_print_code, problem_print_code):
    """ """
    trigger = dash.callback_context.triggered
    trigger_id = trigger[0]["prop_id"].split(".")[0]

    samples = None
    if trigger_id == 'solutions_print_code':
        samples = get_samples(solutions_print_code)

    legs = in_problem_code(problem_print_code)
    fig_space = plot_space(legs, samples)
    fig_time = plot_time(legs, transport, samples)
    fig_diversity = plot_diversity(legs, transport, samples)

    if not fig_time:
        fig_time = fig_diversity = dash.no_update

    return fig_space, fig_time, fig_diversity

# @app.callback(
#     Output("???", "disabled"), # needs all disableds for all user inputs
#     Output("btn_cancel", component_property="style"),
#     Input("btn_solve_cqm", "n_clicks"),
#     Input("solutions_print_human", "value"),)
# def button_control(??, n_intervals):
#     """
#     Enable and disable user input during job submissions.
#     """
#     trigger_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]
#
#     if trigger_id =="???":
#
#         return True, dict()
#
#     if trigger_id =="solutions_print_human":
#
#         return False, dict(display="none")
#
#     return dash.no_update, dash.no_update

@app.callback(
    Output("job_id", "children"),
    [Input("job_submit_time", "children")],
    [State("problem_print_code", "value")],
    [State("max_leg_slope", "value")],
    [State(id, "value") for id in constraint_inputs.keys()],
    [State(id, "value") for id in cqm_inputs.keys()],)
def job_submit(job_submit_time, problem_print_code, max_leg_slope, max_cost, max_time,
    weight_cost, weight_time, weight_slope):
    """
    Submit job.
    Generates the job ID.
    """
    trigger_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]

    if trigger_id =="job_submit_time":

        solver = client.get_solver(supported_problem_types__issubset={"cqm"})
        legs = in_problem_code(problem_print_code)
        cqm = build_cqm(legs, modes, max_leg_slope, max_cost, max_time, \
            weight_cost, weight_time, weight_slope)
        problem_data_id = solver.upload_cqm(cqm).result()

        computation = solver.sample_cqm(problem_data_id,
                    label=f"Examples - Tour Planning, submitted: {job_submit_time}", time_limit=5)

        return computation.wait_id()

    return dash.no_update
#
@app.callback(
    Output('btn_solve_cqm', 'disabled'),
    Output('btn_cancel', component_property='style'),
    Output('wd_job', 'disabled'),
    Output('wd_job', 'interval'),
    Output('wd_job', 'n_intervals'),
    Output('bar_job_status', 'value'),
    Output('bar_job_status', 'color'),
    Output('job_submit_state', 'children'),
    Output('job_sm', 'children'),
    Output('job_submit_time', 'children'),
    Output('job_elapsed_time', 'children'),
    Output('solutions_print_code', 'value'),
    Output("solutions_print_human", "value"),
    Input('btn_solve_cqm', 'n_clicks'),
    Input('wd_job', 'n_intervals'),
    State('job_id', 'children'),
    State('problem_print_code', 'value'),
    State('job_submit_state', 'children'),
    State('job_sm', 'children'),
    State('job_submit_time', 'children'),)
def cqm_submit(n_clicks, n_intervals, job_id, problem_print_code, job_submit_state,
    job_sm, job_submit_time):
    """SM for job submission."""
    trigger_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]

    if not trigger_id in ["btn_solve_cqm", "wd_job"]:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, \
            dash.no_update, dash.no_update, \
            dash.no_update, dash.no_update, \
            dash.no_update, dash.no_update, \
            dash.no_update, dash.no_update

    if trigger_id == "btn_solve_cqm":
        return True, dict(), False, 0.2*1000, 0, \
            job_bar['SUBMITTED'][0], job_bar['SUBMITTED'][1], \
            out_job_submit_state("SUBMITTED"), "SUBMITTED", \
            datetime.datetime.now().strftime("%c"), f"Elapsed: 0 sec.", \
            dash.no_update, dash.no_update

    if job_sm == "SUBMITTED":
        p = Problems(endpoint=client.endpoint, token=client.token)

        try:
            status = p.get_problem_status(job_id)
            label_time = dict(status)["label"].split("submitted: ")[1]
            if label_time == job_submit_time:
                status = status.status.value
                job_submit_state = status
            else:
                status= "SUBMITTED"
                job_submit_state = "SUBMITTED"
        except Exception as err:
            print(err, type(err).__name__)
            status = "SUBMITTED"
            job_submit_state = "SUBMITTED"
        #
        elapsed_time = (datetime.datetime.now() - datetime.datetime.strptime(job_submit_time, "%c")).seconds

        return True, dash.no_update, False, 1*1000, 0, \
            job_bar['SUBMITTED'][0], job_bar['SUBMITTED'][1], \
            out_job_submit_state(job_submit_state), status, \
            dash.no_update, f"Elapsed: {elapsed_time} sec.", \
            dash.no_update, dash.no_update

    if job_sm in ['PENDING', 'IN_PROGRESS']:
        p = Problems(endpoint=client.endpoint, token=client.token)
        status = p.get_problem_status(job_id).status.value
        job_submit_state = status

        sampleset_code = dash.no_update
        sampleset_human = dash.no_update
        hide_button = dash.no_update
        if status == 'IN_PROGRESS':
            hide_button = dict(display='none')
        elif status == 'COMPLETED':
            sampleset = client.retrieve_answer(job_id).sampleset
            sampleset_code = json.dumps(sampleset.to_serializable())
            sampleset_human = out_solutions_human(sampleset)

        elapsed_time = (datetime.datetime.now() - datetime.datetime.strptime(job_submit_time, "%c")).seconds

        return True, hide_button, False, 1*1000, 0, \
            job_bar[status][0], job_bar[status][1], \
            out_job_submit_state(job_submit_state), status, \
            dash.no_update, f"Elapsed: {elapsed_time} sec.", \
            sampleset_code, sampleset_human

    if job_sm in ['COMPLETED', 'CANCELLED', 'FAILED']:
        # Need to enable all buttons
        elapsed_time = (datetime.datetime.now() - datetime.datetime.strptime(job_submit_time, "%c")).seconds

        return False, dash.no_update, True, 0.1*1000, 0, \
            dash.no_update, dash.no_update, \
            dash.no_update, dash.no_update, \
            dash.no_update, f"Elapsed: {elapsed_time} sec.", \
            dash.no_update, dash.no_update

if __name__ == "__main__":
    app.run_server(debug=True)
