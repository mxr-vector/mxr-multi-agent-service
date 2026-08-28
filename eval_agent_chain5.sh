#!/usr/bin/env bash
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
# 等关系构建进程全部结束（手动 setsid 构建在跑）
while pgrep -f "build_relation_index[.]py" > /dev/null; do sleep 120; done
echo "[chain5] relation build done" >> $R/eval_agent_chain.log
# 工具臂：收敛式重跑至 600 条 ok
for i in 1 2 3 4; do
    $PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools.log 2>&1
    N=$(wc -l < $R/longbench_agent_tools_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain5] tools pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
date > $R/EVAL_AGENT_DONE
echo "[chain5] ALL DONE" >> $R/eval_agent_chain.log
