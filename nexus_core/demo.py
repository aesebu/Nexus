from nexus_core import AutonomyLevel, CommandSpec, Nexus, Risk, Step, owner
from nexus_core.intelligence import AgentRole

nx = Nexus()
boss = owner("acme", "alice")

nx.set_goal(boss, "Launch NEXUS MVP", priority=10)
nx.core.models.register(boss, name="chat-main", provider="echo",
                        identifier="echo-1", capabilities={"chat"})
nx.core.policy.register(CommandSpec("report", "nexus.command.execute", Risk.LOW))
nx.core.commands.register_handler("report", lambda c, a: f"report: {c.payload}")

agent = nx.core.agents.create(boss, name="Researcher", role=AgentRole.RESEARCH,
                              instructions="You research topics.",
                              permissions={"nexus.ai.infer"},
                              autonomy=AutonomyLevel.L2_RECOMMEND)
print("agent  :", nx.core.agents.invoke(boss, agent.id, "market size").content)

nx.core.workflows.define(boss, "daily", [Step("r", "report", {"day": "mon"})])
run = nx.core.workflows.run(boss, "daily")
print("flow   :", run.status.value, run.step_results)
print("goals  :", [g.title for g in nx.goals("acme")])
print("audit  :", len(nx.core.audit.for_tenant("acme")), "records, chain ok =",
      nx.core.audit.verify())
