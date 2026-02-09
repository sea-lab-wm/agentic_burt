from pydantic import BaseModel, StrictStr
from langchain_core.callbacks import BaseCallbackHandler
from enum import Enum
from typing import List, Optional
from pathlib import Path
from functools import wraps
from typing import Any
import time

class Entity(str, Enum):
    """
    Defines entities that can execute actions in the application.
    """
    user = "user"
    bot = "bot"

class ActionName(str, Enum):
    """
    Defines names of actions that can be executed during the lifecycle of the application
    """
    user_description = "user_description"
    extract_and_update = "extract_and_update"
    evaluate = "evaluate"
    follow_up = "follow_up"

class MetaData(BaseModel):
    """
    Defines Meta
    """
    latency : str #action latency in ms
    token_consumption : Optional[Any] = None #tracked action involes LLM call, see LLMEvent above for info spec

class Action(BaseModel):
    """
    Defines how agent and user actions are logged.
    Each action in the application must have an entity (see Entity class above), an action name (see ActionName class above), an output (partial state update or user description) and meta data (latency, tokens consumed, etc.)
    """
    entity : Entity
    action_name : ActionName
    output : dict[str, Any] | StrictStr
    meta_data : MetaData

class ConversationTurn(BaseModel):
    turn : int
    actions : List[Action]

class ConversationLogger:
    """
    Captures conversation between user and bot.
    """

    def __init__(self, filepath: str, conversation_id: str):
        self.filepath = Path(filepath)
        self.conversation_id = conversation_id
        self.num_turns : int = 0
        self.conversation : List[ConversationTurn] = [ConversationTurn(turn=self.num_turns, actions=[])]
        

    def add_action_to_conversation(self, entity : Entity, action_name : ActionName, output, meta_data : MetaData):
        """
        Add action to log of current conversation turn. 
        Adds conversation turn to conversation at the beginning of new conversation turn (ie. new user response recieved)
        
        :param entity: Entity that performed the action
        :type entity: Entity
        :param action_name: Name of action that was performed
        :type action_name: ActionName
        :param output: Output of action that was performed
        :type output: str or dict[str, Any]
        """
        if action_name == ActionName.user_description:
            self.num_turns += 1
            self.conversation.append(ConversationTurn(turn=self.num_turns, actions=[]))

        new_action = Action(entity=entity, action_name=action_name, output=output, meta_data=meta_data)
        self.conversation[-1].actions.append(new_action)

    def write_log(self):
        """
        Write contents of self.conversation to log file in JSON format
        """
        with open(self.filepath, "w") as f:
            
            print(self.conversation)

            for action in self.conversation:
                json_str = action.model_dump_json(indent=2)
                f.write(json_str)
                f.write("\n")

def log_action(logger : ConversationLogger, entity : Entity, action_name : ActionName):
    """
    Decorator Factory that allows for traceable per-action logging of application events.
    
    :param logger: Active logger object
    :type logger: ConversationLogger
    :param entity: Entity that performed the action to be logged
    :type entity: Entity
    :param action_name: Name of action to be logged
    :type action_name: ActionName
    """
    def decorator(node_func):
        @wraps(node_func)
        def wrapper(*args, **kwargs):
            #mark timestamp directly before app action performed
            start = time.perf_counter()

            #capture output of application action
            output = node_func(*args, **kwargs)

            #calculate and store latency of app action in ms
            action_latency = f"{(time.perf_counter() - start)} s"
            meta_data = MetaData(latency=action_latency)
            logger.add_action_to_conversation(entity=entity, action_name=action_name, output=output, meta_data=meta_data)

            return output
        return wrapper
    return decorator






    
    