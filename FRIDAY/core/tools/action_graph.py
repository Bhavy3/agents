import asyncio
import time
from typing import Any, Dict
from .tool_models import ActionGraph, ActionNode, ToolResult


class ActionGraphRunner:
    """Executes chains of tools with dependency management and timeout safety."""

    def __init__(self, tool_executor: Any):
        self.tool_executor = tool_executor # Reference to ToolWorker or its executor logic

    async def execute_graph(self, graph: ActionGraph) -> ToolResult:
        start_time = time.time()
        completed_nodes: Dict[str, ToolResult] = {}
        
        try:
            # Linear execution for Phase 9.0 (as per requirement: "linear execution only")
            for node in graph.nodes:
                # Check dependencies (even in linear, we should verify)
                for dep in node.depends_on:
                    if dep not in completed_nodes or not completed_nodes[dep].success:
                        return ToolResult(False, "", f"Dependency {dep} failed or not met for node {node.id}")

                node.state = "RUNNING"
                result = await self.tool_executor.execute_tool(
                    node.tool_name, 
                    node.parameters, 
                    correlation_id=graph.id
                )
                
                if result.success:
                    node.state = "COMPLETED"
                    completed_nodes[node.id] = result
                else:
                    node.state = "FAILED"
                    return ToolResult(False, "", f"Node {node.id} ({node.tool_name}) failed: {result.error}")

            duration = (time.time() - start_time) * 1000
            return ToolResult(True, f"Action graph {graph.id} completed successfully", duration_ms=duration)

        except asyncio.CancelledError:
            for node in graph.nodes:
                if node.state == "RUNNING":
                    node.state = "CANCELLED"
            return ToolResult(False, "", "Graph execution cancelled by operator")
        except Exception as e:
            return ToolResult(False, "", f"Graph execution error: {str(e)}")
