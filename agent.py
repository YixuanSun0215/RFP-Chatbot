import streamlit as st
import boto3
import random
import docx  # For handling DOCX files
from PyPDF2 import PdfReader  # For handling PDF files
import re


# Constants
REGION = "us-east-1"
AGENT_ID = "QC79LBL2C1"
AGENT_ALIAS_ID = "K7MTXRNYQU" # v3: "TRWVSCKGXA", v5: "EXXPUSCFYP", v6: "K7MTXRNYQU"

# Setup bedrock client
bedrock_agent_runtime = boto3.client(
    service_name="bedrock-agent-runtime",
    region_name=REGION,
)

def generate_random_15digit():
    return "".join(str(random.randint(0, 9)) for _ in range(15))

def process_stream(stream):
    output = ""
    try:
        if "chunk" in stream:
            text = stream["chunk"]["bytes"].decode("utf-8")
            output += text
    except Exception as e:
        output += f"Error processing stream: {e}\n"
    return output


def invoke_agent(query):
    # Check if a session ID already exists, if not, create one
    if 'session_id' not in st.session_state:
        st.session_state.session_id = generate_random_15digit()
    
    try:
        response = bedrock_agent_runtime.invoke_agent(
            sessionState={
                "sessionAttributes": {},
                "promptSessionAttributes": {},
            },
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=st.session_state.session_id,  # Use the stored session ID
            endSession=False,
            enableTrace=True,
            inputText=query,
        )

        results = response.get("completion", [])
        agent_output = ""
        for stream in results:
            agent_output += process_stream(stream)
        return agent_output, []  # Returning an empty list for citations for now
    except Exception as e:
        st.error(f"Error invoking agent: {e}")
        return "Error invoking agent.", []


# Function to upload and read file content
def upload_file(file):
    if file is not None:
        file_type = file.name.split('.')[-1].lower()
        if file_type in ['pdf', 'docx']:
            context = read_file(file, file_type)
        else:
            context = ""
    else:
        context = ""
    
    return context


def read_file(file, file_type):
    if file_type == 'pdf':
        try:
            reader = PdfReader(file)
            text = ' '.join([page.extract_text() for page in reader.pages])
            return text
        except Exception as e:
            return ""
    elif file_type == 'docx':
        try:
            doc = docx.Document(file)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return '\n'.join(full_text)
        except Exception as e:
            return ""  


def extract_questions(text):
    pattern = r'\d+\.\s(.*?)(?=\d+\.\s|$)|(?:^|\n)(.*?\?)'
    matches = re.findall(pattern, text, re.DOTALL)
    questions = [match[0] or match[1] for match in matches]
    additional_questions = re.findall(r'(?<!\d\.\s)(^[A-Z].*?$)', text, re.MULTILINE)
    questions.extend(additional_questions)
    return [q.strip() for q in questions if q.strip()]


# Streamlit UI
st.set_page_config(page_title="AWS Bedrock Chatbot", page_icon=":robot_face:")

# Add logo
st.image("logo.png", width=200)  # Replace "logo.png" with your image file or URL

st.title("BlocPower Chatbot")


# Initialize session state for chat history
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'state' not in st.session_state:
    st.session_state.state = 1
if 'last_state' not in st.session_state:
    st.session_state.last_state = 0
if 'question_list' not in st.session_state:
    st.session_state.question_list = []
if 'program_name' not in st.session_state:
    st.session_state.program_name = ""

st.markdown(
    """
    **Enter your question/answer:**

    - First, tell me the agency and the program hosting the RFP to which we need to respond.
    - Then, follow up with any additional information or questions you have.
    """
)

query = st.text_input("Your input:")
file = st.file_uploader(f"Upload your document:", type=['pdf', 'docx'], key="file_uploader")

if st.button("Submit", key="submit_query"):
    if query:
        with st.spinner("Processing..."):
            response_text = ""
            citations = []

            # State 1: Provide information on progarm
            if st.session_state.state == 1:
                st.session_state.program_name = query
                user_command = f"Use Internet Search to provide information on {st.session_state.program_name}."
                response_text, citations = invoke_agent(user_command)
                specific_question = "Is this information correct? Please respond with 'Correct' or 'Incorrect'."
                response_text += "\n" + specific_question
                st.session_state.state = 3

            # State 3: Validate result from state 1
            elif st.session_state.state == 3:
                if query.lower() in ["correct", "yes"]:
                    response_text = "Please upload a word document, PDF, or link to the application."
                    st.session_state.state = 4
                elif query.lower() in ["incorrect", "no"]:
                    response_text = "Please provide a short summary of the correct agency and program details."
                    st.session_state.state = 7
                else:
                    response_text = f"Is the above information about {st.session_state.program_name} correct? Please respond with 'Correct' or 'Incorrect'. "
                    st.session_state.state = 3
            
            # state 4: Read and parse the file into questions
            elif st.session_state.state == 4:
                context = upload_file(file)
                new_query = query + "\n" + context
                response_text, citations = invoke_agent(new_query)
                specific_question = "Is this question list complete? Please respond with 'Yes' or 'No'."
                response_text = specific_question + "\n" + response_text
                st.session_state.state = 5
            
            # state 5: check if the questions list is complete
            elif st.session_state.state == 5:
                if query.lower() in ["correct", "yes"]:
                    response_text = "The next step will be reformatting the questions. Please provide the reformat instruction."
                    st.session_state.state = 6
                elif query.lower() in ["incorrect", "no"]:
                    response_text = "Please provide a list for all the questions."
                    st.session_state.state = 8
                else: 
                    response_text = "Is the question list complete? Please respond with 'Yes' or 'No'. "
                    st.session_state.state = 5
            
            # state 6: Reformatting the questions as BlocPower
            elif st.session_state.state == 6:
                response_text, citations = invoke_agent(query)
                st.session_state.question_list = extract_questions(response_text)
                specific_question = "I will start to answer the following questions. Enter 'Yes' to confirm, 'No' to cancel. "
                response_text = specific_question + response_text + f" The number of questions is {len(st.session_state.question_list)}."
                st.session_state.chat_history.append({"query": query, "response": response_text, "from_state_9": False})
                st.session_state.state = 9
            
            # state 7: User provide information on the C2C program
            elif st.session_state.state == 7:
                user_command = f"The information you provided on {st.session_state.program_name} is not complete or correct. Here's the information provided by the user on the program: "
                new_query = user_command + "\n" + query
                response_text, citations = invoke_agent(new_query)
                st.session_state.state = 3
            
            # state 8: User provide complete questions list
            elif st.session_state.state == 8:
                user_command = "The question list you just extracted is not complete or correct. Here's the questions list provided by the user: "
                query = user_command + "\n" + query
                response_text, citations = invoke_agent(query)
                st.session_state.state = 5
            
            # state 9: answer questions
            elif st.session_state.state == 9:
                st.session_state.last_state = 6
                if query.lower() in ["yes"]:
                    if len(st.session_state.question_list) == 0:
                        response_text = "No Questions Detected. Ask me a question."
                        st.session_state.chat_history.append({"query": query, "response": response_text, "from_state_9": True})
                        st.markdown(f"**You:** {query}")
                        st.markdown(f"**Bot:** {response_text}")
                        st.markdown("---")
                    else:
                        user_command = "Refer to the knowledge base and answer the following question with the first person 'we' instead of the third person 'Blocpower'."
                        for question in st.session_state.question_list:
                            new_question = user_command + question
                            response_text, citations = invoke_agent(new_question)
                            # Append current query and response to chat history
                            st.session_state.chat_history.append({"query": question, "response": response_text, "from_state_9": True})
                            st.markdown(f"**You:** {question}")
                            st.markdown(f"**Bot:** {response_text}")
                            st.markdown("---")
                        st.session_state.question_list = []
                    st.session_state.state = 10
                    st.session_state.last_state = 9
                    query = ""

                elif query.lower() in ["no"]:
                    response_text = "Question answering canceled."
                    st.session_state.chat_history.append({"query": query, "response": response_text, "from_state_9": True})
                    st.markdown(f"**You:** {query}")
                    st.markdown(f"**Bot:** {response_text}")
                    st.markdown("---")
                    st.session_state.state = 10
                    st.session_state.last_state = 9
                    query = ""

                else:
                    response_text = "Enter 'Yes' to start answer the questions, 'No' to cancel."        
                    st.session_state.chat_history.append({"query": query, "response": response_text, "from_state_9": True})
                    st.markdown(f"**You:** {query}")
                    st.markdown(f"**Bot:** {response_text}")
                    st.markdown("---")
                    st.session_state.last_state = 9      
                
            elif st.session_state.state == 10: 
                response_text, citations = invoke_agent(query)
                st.session_state.last_state = 10

            if st.session_state.state != 9 and query:
                # Append current query and response to chat history
                st.session_state.chat_history.append({"query": query, "response": response_text, "from_state_9": False})

            # Display chat history
            for chat in reversed(st.session_state.chat_history):
                if st.session_state.last_state == 9: 
                    if not chat.get("from_state_9", False):
                        st.markdown(f"**You:** {chat['query']}")
                        st.markdown(f"**Bot:** {chat['response']}")
                        st.markdown("---")
                else:
                    st.markdown(f"**You:** {chat['query']}")
                    st.markdown(f"**Bot:** {chat['response']}")
                    st.markdown("---")

            # Display citations in an expander below the chat history, if any
            if citations:
                with st.expander("Citations", expanded=False):
                    for index, citation in enumerate(citations, start=1):
                        text = citation['generatedResponsePart']['textResponsePart']['text']
                        st.markdown(f"\n{text}\n")
                        for ref in citation['retrievedReferences']:
                            content_text = ref['content']['text']
                            location_uri = ref['location']['s3Location']['uri']
                            st.markdown(f"- [{content_text}]({location_uri})")
                        if index < len(citations):
                            st.markdown("---")
            else:
                st.write("No citations available.")
