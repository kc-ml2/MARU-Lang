"""
MCP Client Agent - Base class for MCP client connections
"""
import json
from typing import Dict, Any, Optional, List
from mcp import ClientSession, StdioServerParameters
from mcp.types import TextContent, CallToolResult, ListToolsResult
from mcp.client.stdio import stdio_client
from maru_lang.pluggable.agents.base import BaseAgent
from maru_lang.models.agents import AgentResult
from maru_lang.pluggable.models import AgentConfig


class MCPClientAgent(BaseAgent):
    """
    Base class for MCP client agents
    Handles connection to external MCP servers
    """

    def __init__(
        self,
        name: str, 
        config: AgentConfig,
    ):
        """
        Initialize MCP client agent
        """
        super().__init__(name, config)
        self.mcp_config = config.mcp_config

    async def _setup(self) -> None:
        """Setup MCP client agent"""
        pass

    async def execute(
        self,
        question: str,
        **kwargs
    ) -> AgentResult:
        """
        Execute MCP tool via LLM agent pattern

        Two modes:
        1. LLM mode (user_message provided): LLM decides which tool to call

        Args:
            question: User message for LLM to process
            **kwargs: Additional parameters

        Returns:
            AgentResult with tool execution outcome
        """
        server = StdioServerParameters(
            command=self.mcp_config.command,
            args=self.mcp_config.args,
            env=self.mcp_config.env
        )
        try:
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize the connection
                    await session.initialize()
                    tools = await session.list_tools()
                    llm_tools = self._convert_mcp_tools_to_llm_format(tools)

                    if not llm_tools:
                        return AgentResult(
                            success=False,
                            result="",
                            error="No MCP tools available"
                        )
                        
                    try:
                        system_prompt = "You are a helpful assistant with access to tools."
                        user_prompt = question
                        prompts = self.config.prompts if self.config.prompts else None
                        if prompts:
                            system_prompt = prompts.system_prompt
                            user_prompt = prompts.user_prompt_template.format(question=question)
                    except Exception as e:
                        pass
                    finally:
                        system_prompt = system_prompt
                        user_prompt = user_prompt

                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]

                    # 5. Get override parameters
                    override_params = self.get_override_params()

                    # Call LLM with current messages (with fallback)
                    response = await self.request_with_tools_and_fallback(
                        messages=messages,
                        tools=llm_tools,
                        tool_choice="auto",
                        **override_params
                    )
                    tool_calls = response.get('tool_calls', [])

                    # Execute tool calls on MCP server
                    tool_results = await self._execute_tool_calls(tool_calls, session)

                    # Check if any tool calls were made
                    if not tool_calls:
                        return AgentResult(
                            success=False,
                            result="",
                            error="No tool calls were made by LLM"
                        )

                    # Check if all tool executions were successful
                    failed_tools = [r for r in tool_results if not r['success']]

                    # tool_results to text -> response
                    response_parts = []
                    for tool_result in tool_results:
                        if tool_result['success']:
                            content = tool_result['result']
                            # content is list of TextContent objects
                            if isinstance(content, list):
                                for item in content:
                                    if hasattr(item, 'text'):
                                        response_parts.append(item.text)
                                    else:
                                        response_parts.append(str(item))
                            elif hasattr(content, 'text'):
                                response_parts.append(content.text)
                            else:
                                response_parts.append(str(content))
                        else:
                            response_parts.append(f"Error: {tool_result.get('error', 'Unknown error')}")

                    response_text = "\n\n".join(response_parts)

                    # If any tool failed, return failure with details
                    if failed_tools:
                        error_details = "; ".join([
                            f"{t['tool']}: {t.get('error', 'Unknown error')}"
                            for t in failed_tools
                        ])
                        return AgentResult(
                            success=False,
                            result=response_text,  # Include partial results
                            error=f"MCP tool execution failed: {error_details}",
                            data={
                                "tool_calls": tool_calls,
                                "tool_results": tool_results
                            },
                            metadata={
                                "agent": self.name,
                                "tools_called": len(tool_calls),
                                "failed_tools": len(failed_tools)
                            }
                        )

                    # All tools succeeded
                    return AgentResult(
                        success=True,
                        result=response_text,
                        data={
                            "tool_calls": tool_calls,
                            "tool_results": tool_results
                        },
                        metadata={
                            "agent": self.name,
                            "tools_called": len(tool_calls)
                        }
                    )

        except Exception as e:
            return AgentResult(
                success=False,
                result="",
                error=f"MCP session not established: {str(e)}"
            )

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        session: ClientSession
    ) -> List[Dict[str, Any]]:
        """Execute multiple tool calls on MCP server"""
        results = []

        for tool_call in tool_calls:
            try:
                # Extract tool name and arguments
                function = tool_call.get('function', {})
                tool_name = function.get('name')
                arguments = function.get('arguments', {})

                # Call MCP server
                result = await session.call_tool(
                    name=tool_name,
                    arguments=arguments
                )
                results.append({
                    "tool": tool_name,
                    "success": True,
                    "result": result.content if hasattr(result, 'content') else str(result)
                })

            except Exception as e:
                results.append({
                    "tool": tool_name if 'tool_name' in locals() else "unknown",
                    "success": False,
                    "error": str(e)
                })
        return results

    def _convert_mcp_tools_to_llm_format(
        self,
        tools: ListToolsResult
    ) -> List[Dict[str, Any]]:
        """
        Convert MCP tools to LLM-compatible tool format

        MCP format: {name, description, inputSchema}
        LLM format: {type: "function", function: {name, description, parameters}}
        """
        llm_tools = []
        
        for tool in tools.tools:
            llm_tool = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            }
            llm_tools.append(llm_tool)
        return llm_tools
        

    def get_capabilities(self) -> Dict[str, Any]:
        """Return agent capabilities based on MCP config"""
        return {
            "name": self.name,
            "description": f"MCP client agent connected to {self.mcp_config.command}",
            "transport": self.mcp_config.transport
        }
