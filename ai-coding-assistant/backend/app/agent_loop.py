import json
import logging
from typing import Optional, List, Dict, Any
from app.model_manager import model_manager
from app.workspace_tools import TOOLS_SCHEMA, AVAILABLE_TOOLS

logger = logging.getLogger(__name__)

async def run_agent(prompt: str, system_prompt: str, max_iterations: int = 15) -> str:
    """Run an autonomous ReAct loop with the agent."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    for i in range(max_iterations):
        logger.info(f"Agent Loop Iteration {i+1}/{max_iterations}")
        
        # 1. Ask the model
        response_msg = await model_manager.chat_with_tools(messages, tools=TOOLS_SCHEMA)
        
        # If response_msg is empty for some reason, bail out
        if not response_msg:
            return "Error: Received empty response from model."
            
        # 2. Add assistant's response to history
        messages.append(response_msg)
        
        # 3. Check for tool calls
        tool_calls = response_msg.get("tool_calls")
        if not tool_calls:
            # If the model didn't call any tools, it means it's done.
            return response_msg.get("content", "")
            
        # 4. Execute tool calls
        for tc in tool_calls:
            func = tc.get("function", {})
            func_name = func.get("name")
            arguments = func.get("arguments", {})
            
            # Parse arguments if it's a string
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except Exception as e:
                    logger.error(f"Failed to parse tool arguments: {e}")
                    arguments = {}
                    
            logger.info(f"Agent executing tool: {func_name} with args: {arguments}")
            
            if func_name in AVAILABLE_TOOLS:
                try:
                    tool_result = AVAILABLE_TOOLS[func_name](**arguments)
                except Exception as e:
                    tool_result = f"Error executing tool internally: {str(e)}"
            else:
                tool_result = f"Error: Tool '{func_name}' not found."
                
            logger.info(f"Tool {func_name} returned: {tool_result[:200]}...")
                
            # 5. Add tool result to history
            messages.append({
                "role": "tool",
                "name": func_name,
                "content": str(tool_result)
            })
            
    return "Error: Agent reached maximum iterations without completing the task. The problem was too complex or the agent got stuck in a loop."
