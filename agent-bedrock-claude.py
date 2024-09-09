import streamlit as st
import boto3
import random
import docx  # For handling DOCX files
from PyPDF2 import PdfReader  # For handling PDF files
import re
import json
from botocore.exceptions import ClientError



# Constants
REGION = "us-east-1"
AGENT_ID = "QC79LBL2C1"
AGENT_ALIAS_ID = "K7MTXRNYQU"  # v3: "TRWVSCKGXA", v5: "EXXPUSCFYP", v6: "K7MTXRNYQU"
MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
# MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Setup bedrock client
bedrock_agent_runtime = boto3.client(
    service_name="bedrock-agent-runtime",
    region_name=REGION,
)
bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
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
    if "session_id" not in st.session_state:
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

        # print(response)
        # # Print the trace JSON
        # trace_data = response.get("trace", {})
        # print(json.dumps(trace_data, indent=4))  # Pretty print the trace JSON

        results = response.get("completion", [])
        agent_output = ""
        for stream in results:
            print(stream)
            agent_output += process_stream(stream)
        return agent_output, []  # Returning an empty list for citations for now
    except Exception as e:
        st.error(f"Error invoking agent: {e}")
        return "Error invoking agent.", []



def invoke_model(prompt,  max_tokens=30000, temperature=0.5):
    # Format the request payload using the model's native structure.
    native_request = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    }

    # Convert the native request to JSON.
    request = json.dumps(native_request)

    try:
        # Invoke the model with the request.
        response = bedrock_runtime.invoke_model(modelId=MODEL_ID, body=request)
    except (ClientError, Exception) as e:
        print(f"ERROR: Can't invoke '{MODEL_ID}'. Reason: {e}")
        exit(1)

    # Decode the response body.
    model_response = json.loads(response["body"].read())

    # Extract and print the response text.
    response_text = model_response["content"][0]["text"]
    return response_text


# Function to upload and read file content
def upload_file(file):
    if file is not None:
        file_type = file.name.split(".")[-1].lower()
        if file_type in ["pdf", "docx"]:
            context = read_file(file, file_type)
        else:
            context = ""
    else:
        context = ""

    return context


def read_file(file, file_type):
    if file_type == "pdf":
        try:
            reader = PdfReader(file)
            text = " ".join([page.extract_text() for page in reader.pages])
            return text
        except Exception as e:
            return ""
    elif file_type == "docx":
        try:
            doc = docx.Document(file)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return "\n".join(full_text)
        except Exception as e:
            return ""


def extract_questions(text):
    pattern = r"\d+\.\s(.*?)\s*$"
    questions = re.findall(pattern, text, re.MULTILINE)
    return questions


# Streamlit UI
st.set_page_config(page_title="AWS Bedrock Chatbot", page_icon=":robot_face:")

# Add logo
st.image("logo.png", width=200)  # Replace "logo.png" with your image file or URL

st.title("RFP Engine")


# Initialize session state for chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "state" not in st.session_state:
    st.session_state.state = 1
if "last_state" not in st.session_state:
    st.session_state.last_state = 0
if "question_list" not in st.session_state:
    st.session_state.question_list = []
if "program_name" not in st.session_state:
    st.session_state.program_name = ""
if "response" not in st.session_state:
    st.session_state.response = ""

st.markdown(
    """
    **Enter your question/answer:**

    - First, tell me the agency and the program hosting the RFP to which we need to respond.
    - Then, follow up with any additional information or questions you have.
    """
)

query = st.text_input("Your input:")
file = st.file_uploader(
    f"Upload your document:", type=["pdf", "docx"], key="file_uploader"
)

if st.button("Submit", key="submit_query"):
    if query or file:
        with st.spinner("Processing..."):
            response_text = ""
            citations = []

            # State 1: Provide information on progarm
            if st.session_state.state == 1:
                st.session_state.program_name = query
                user_command = f"Use Internet Search to provide information on {st.session_state.program_name}."
                # response_text, citations = invoke_agent(user_command)
                response_text = invoke_model(user_command)
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
                if context:
                    query = f"We, BlocPower, need to respond to {st.session_state.program_name} program's request for proposal (RFP). Here's the context for application. Firstly, write a summary of the RFP. Secondly, read and parse the whole context, extract and list all the questions that blocpower needs to answer. "
                    user_command = "Convert the second person pronoun 'you' in the question to the third person pronoun 'BlocPower'. List all converted questions and mark them with numbers at the beginning and a period at the end. "
                    new_query = query + user_command + context
                    response = invoke_model(new_query)
                    st.session_state.response = response
                    specific_question = "Is this question list complete? Please respond with 'Yes' or 'No'."
                    response_text = specific_question + "\n" + response
                    st.session_state.state = 5
                    st.session_state.file_processed_4 = True
                else:
                    response_text = "No file content found. Please upload a valid file."

            # state 5: check if the questions list is complete
            elif st.session_state.state == 5:
                if query.lower() in ["correct", "yes"]:
                    st.session_state.question_list = extract_questions(
                        st.session_state.response
                    )
                    specific_question = "I will start to answer the following questions. Enter 'Yes' to confirm, 'No' to cancel. "
                    response_text = specific_question + str(
                        st.session_state.question_list
                    )
                    st.session_state.chat_history.append(
                        {
                            "query": query,
                            "response": response_text,
                            "from_state_9": False,
                        }
                    )
                    st.session_state.state = 9
                elif query.lower() in ["incorrect", "no"]:
                    response_text = "Please provide a list for all the questions."
                    st.session_state.state = 8
                else:
                    response_text = "Is the question list complete? Please respond with 'Yes' or 'No'. "
                    st.session_state.state = 5

            # state 7: User provide information on program
            elif st.session_state.state == 7:
                user_command = f"The information you provided on {st.session_state.program_name} is not complete or correct. Here's the information provided by the user on the program: "
                new_query = user_command + "\n" + query
                # response_text, citations = invoke_agent(new_query)
                response_text = invoke_model(new_query)
                st.session_state.state = 3

            # state 8: User provide complete questions list
            elif st.session_state.state == 8:
                user_command = "The question list you just extracted is not complete or correct. Here's the questions list provided by the user. Convert the second person pronoun 'you' in the question to the third person pronoun 'BlocPower'. List all converted questions and mark them with numbers."
                new_query = user_command + query
                response_text = invoke_model(new_query)
                st.session_state.response = response_text
                st.session_state.state = 5

            # state 9: answer questions
            elif st.session_state.state == 9:
                st.session_state.last_state = 5
                if query.lower() in ["yes"]:
                    if len(st.session_state.question_list) == 0:
                        response_text = "No Questions Detected. Ask me a question."
                        st.session_state.chat_history.append(
                            {
                                "query": query,
                                "response": response_text,
                                "from_state_9": True,
                            }
                        )
                        st.markdown(f"**You:** {query}")
                        st.markdown(f"**Bot:** {response_text}")
                        st.markdown("---")
                    else:
                        user_command = "Refer to the knowledge base and answer the following question with the first person 'we' instead of the third person 'Blocpower'."
                        for question in st.session_state.question_list:
                            new_question = user_command + question
                            response_text, citations = invoke_agent(new_question)
                            # Append current query and response to chat history
                            st.session_state.chat_history.append(
                                {
                                    "query": question,
                                    "response": response_text,
                                    "from_state_9": True,
                                }
                            )
                            st.markdown(f"**You:** {question}")
                            st.markdown(f"**Bot:** {response_text}")
                            st.markdown("---")
                        st.session_state.question_list = []
                    st.session_state.state = 10
                    st.session_state.last_state = 9
                    query = ""

                elif query.lower() in ["no"]:
                    response_text = "Question answering canceled."
                    st.session_state.chat_history.append(
                        {
                            "query": query,
                            "response": response_text,
                            "from_state_9": True,
                        }
                    )
                    st.markdown(f"**You:** {query}")
                    st.markdown(f"**Bot:** {response_text}")
                    st.markdown("---")
                    st.session_state.state = 10
                    st.session_state.last_state = 9
                    query = ""

                else:
                    response_text = (
                        "Enter 'Yes' to start answer the questions, 'No' to cancel."
                    )
                    st.session_state.chat_history.append(
                        {
                            "query": query,
                            "response": response_text,
                            "from_state_9": True,
                        }
                    )
                    st.markdown(f"**You:** {query}")
                    st.markdown(f"**Bot:** {response_text}")
                    st.markdown("---")
                    st.session_state.last_state = 9

            elif st.session_state.state == 10:
                if file:
                    context = upload_file(file)
                    if context:
                        user_command = "Based on the uploaded document, answer the following question with the first person 'we' instead of the third person 'Blocpower'."
                        new_query = user_command + "\n" + query + " " + context
                        claude_response = invoke_model(new_query)
                        combined_query = f"The user asked: '{query}'. Claude's response was: '{claude_response}'. Please provide an enhanced answer considering the knowledge base."
                        agent_response, citations = invoke_agent(combined_query)

                        response_text = f"**Claude's Response:**\n{claude_response}\n\n**Agent's Enhanced Response:**\n{agent_response}"
                    else:
                        response_text = (
                            "No file content found. Please upload a valid file."
                        )
                elif not file:
                    user_command = "Answer the following question with the first person 'we' instead of the third person 'Blocpower'. "
                    new_query = user_command + query
                    response_text, citations = invoke_agent(new_query)

                st.session_state.last_state = 10

            if st.session_state.state != 9 and query:
                # Append current query and response to chat history
                st.session_state.chat_history.append(
                    {"query": query, "response": response_text, "from_state_9": False}
                )

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
                        text = citation["generatedResponsePart"]["textResponsePart"][
                            "text"
                        ]
                        st.markdown(f"\n{text}\n")
                        for ref in citation["retrievedReferences"]:
                            content_text = ref["content"]["text"]
                            location_uri = ref["location"]["s3Location"]["uri"]
                            st.markdown(f"- [{content_text}]({location_uri})")
                        if index < len(citations):
                            st.markdown("---")
            else:
                st.write("No citations available.")
