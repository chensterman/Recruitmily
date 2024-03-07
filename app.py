import re
import requests
import json
import streamlit as st
import os
import sys
from dotenv import load_dotenv

from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.callbacks import StreamlitCallbackHandler
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Load environment variables
load_dotenv()

# LinkedIn initial authentication
def authenticate():    
    # Grab these from config or env variables
    username = os.environ.get("LI_USERNAME", "")
    password = os.environ.get("LI_PASSWORD", "")
    csrf = os.environ.get("LOGIN_CSRF_PARAM", "")
    # Build request data
    url = "https://www.linkedin.com/uas/login-submit"
    postdata = {
            'session_key': username,
            'session_password': password,
            'loginCsrfParam': csrf,
            }
    cookies = {'bcookie': 'v=2&%s' % csrf}
    # Login Request
    r = requests.post(url, postdata, cookies=cookies, allow_redirects=False)
    # LinkedIn Session Key
    try:
        session = r.cookies['li_at']
        print(session)
        if(session):
            cookie = {'li_at': session}
            return cookie
        else:
            sys.exit("[Fatal] Could not authenticate to linkedin. Set credentials in your environment variables.")
    except:
        sys.exit("[Fatal] Could not authenticate to linkedin. Set credentials in your environment variables.")

# Authenticate and get LinkedIn cookies
cookies = authenticate()

# Set LLM to be used by agents
llm = ChatOpenAI(temperature=0, model="gpt-3.5-turbo-1106", streaming=True)

# Set up agent tooling
@tool
def profileLookup(linkedin_url: str):
    """
    Given a LinkedIn user profile link, useful for extraction of the profile information as text.
    """
    pattern = r"https://www.linkedin.com/in/([\w-]+)/"
    match = re.match(pattern, linkedin_url)
    userslug = match.group(1)
    url = "https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity=%s&decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-35" % userslug
    headers = {'Csrf-Token':'ajax:3972979001005769271'}
    headers['X-RestLi-Protocol-Version'] = '2.0.0' 
    cookies['JSESSIONID'] = 'ajax:3972979001005769271'
    r = requests.get(url, cookies=cookies, headers=headers)
    profresp = r.text.encode('UTF-8')
    profresp = json.loads(profresp)    
    with open('test.json', 'w') as file:
        json.dump(profresp, file)
    # Extract Basic Profile Info 
    data_positions = []
    data_skills = []
    data_schools = []
    data_fname = profresp['elements'][0]['firstName']
    data_lname = profresp['elements'][0]['lastName']
    data_location = profresp['elements'][0]['geoLocation']['geo']['defaultLocalizedName']
    data_industry = profresp['elements'][0]['industry']['name']
    data_headline = profresp['elements'][0]['headline']
    data_summary = "N/A Summary" if 'summary' not in profresp['elements'][0] else profresp['elements'][0]['summary']
    for company in profresp['elements'][0]['profilePositionGroups']['elements']:
        for position in company['profilePositionInPositionGroup']['elements']:
            description = '' if 'description' not in position else position['description']
            startMonth = '' if not 'month' in position['dateRange']['start'] else position['dateRange']['start']['month']
            dateStart = str(startMonth) + '/' + str(position['dateRange']['start']['year'])
            dateEnd = 'Present' if 'end' not in position['dateRange'] else str(position['dateRange']['end']['month']) + '/' + str(position['dateRange']['end']['year'])
            data_positions.append("%s: %s, %s - %s\n%s\n" % (position['companyName'], position['title'], dateStart, dateEnd, description))
    for d in profresp['elements'][0]['profileEducations']['elements']:
        fieldOfStudy = 'N/A FieldOfStudy' if 'fieldOfStudy' not in d else d['fieldOfStudy']
        degreeName = 'N/A DegreeName' if 'degreeName' not in d else d['degreeName']
        data_schools.append("%s: %s, %s" % (d['schoolName'], fieldOfStudy, degreeName))
    # Collect ALL profile skills
    url = "https://www.linkedin.com/voyager/api/identity/profiles/%s/skillCategory?includeHiddenEndorsers=true" % userslug
    headers = {'Csrf-Token':'ajax:3972979001005769271'}
    headers['X-RestLi-Protocol-Version'] = '2.0.0' 
    cookies['JSESSIONID'] = 'ajax:3972979001005769271'
    r = requests.get(url, cookies=cookies, headers=headers)
    skillresp = r.text.encode('UTF-8')
    skillresp = json.loads(skillresp)
    for e in skillresp['elements']:
        for s in e['endorsedSkills']:
            data_skills.append("%s (%s endorsements)" % (s['skill']['name'], s['endorsementCount']))
    # Write Profile Report
    pout = "%s %s (%s)\n" % (data_fname, data_lname, data_headline) 
    pout = pout + "\n"
    pout = pout + "Location: %s\n" % data_location
    pout = pout + "Industry: %s\n" % data_industry
    pout = pout + "\n"
    pout = pout + "ABOUT:\n---------------------\n"
    pout = pout + data_summary + "\n"
    pout = pout + "\nEDUCATION:\n---------------------\n"
    for s in data_schools:
        pout = pout + "%s\n" % s
    pout = pout + "\nEXPERIENCE:\n---------------------\n"
    for c in data_positions:
        pout = pout + "%s\n" % c
    pout = pout + "\nSKILLS:\n---------------------\n"
    for sk in data_skills:
        pout = pout + "%s\n" % sk
    return pout

system_prompt = """
You are recruiter's assistant and will help select potential SDE II candidates for Amazon.

The type of software engineering candidates we are looking are based on the following criteria:
Candidates have extensive backend skills and are actively seeking employment. We require 4+ years industry backend dev
experience, 2+ years system architecture, and open to working in the AWS and Seattle. 3+ years of their work experience
must be in the US or Canada. BE SURE TO CONSIDER THE NUMBER OF YEARS OF BACKEND EXPERIENCE THEY HAVE. Exclude Google and Meta 
and current/past Amazon employees. Graduation year should be before 2018 or before, and in a field related to computer science or STEM. 

We are looking for the following skills included in the profile:
REST API, Java, C++, C#, Python, Go, system design experience, mentoring experience.

We are not looking for candidates with focuses on any of the following fields:
Machine learning, data engineer, embedded, front-end development, consulting.

Given a LinkedIn profile link of an SDE candidate, provide a rating out of 10 based on our criteria and an explanation for your rating.
"""
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            system_prompt,
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ]
)
agent = create_openai_functions_agent(llm=llm, tools=[profileLookup], prompt=prompt)
agent_executor = AgentExecutor(agent=agent, tools=[profileLookup])

# Set up Streamlit UI
st.set_page_config(page_title="Recruitmily.ai", page_icon="💅")
st.title("💅 Recruitmily.ai")
st.write ("Feed me any LinkedIn link and I'll analyze it!")

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "Hi Emily :)\nHow can I help you?"}]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if user_prompt := st.chat_input(placeholder="What is this data about?"):
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    st.chat_message("user").write(user_prompt)

    with st.chat_message("assistant"):
        st_callback = StreamlitCallbackHandler(st.container(), expand_new_thoughts=False)
        response = agent_executor.invoke(
            {"chat_history": st.session_state.messages}, 
            {"callbacks": [st_callback]},
        )
        st.session_state.messages.append({"role": "assistant", "content": response["output"]})
        if len(st.session_state.messages) > 10:
            st.session_state.messages.pop(0)
            st.session_state.messages.pop(0)
        st.write(response["output"])