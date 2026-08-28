#!/usr/bin/env bash
# agentic-relation-retrieval 自治链（重启安全版）：
#   关系构建（断点续建，多轮兜底）→ 工具臂评测（收敛重跑）→ EVAL_AGENT_DONE
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval

# 1) 关系构建：串行多轮（进度表断点 + failed 块重试），严格按 DB chat 角色模型
for i in 1 2 3 4 5 6; do
    $PY build_relation_index.py --concurrency 8 >> $R/build_relation_index.log 2>&1
    echo "[chain6] build pass $i rc=$?" >> $R/eval_agent_chain.log
    sleep 30
done

# 2) 工具臂：收敛式重跑至 600 条 ok（增量落盘，宕机可续）
for i in 1 2 3 4; do
    $PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools.log 2>&1
    N=$(wc -l < $R/longbench_agent_tools_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain6] tools pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done

date > $R/EVAL_AGENT_DONE
echo "[chain6] ALL DONE" >> $R/eval_agent_chain.log
