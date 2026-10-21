# 验证说明

以下命令在仓库根目录执行。需要 Node.js、Python 3.11+、Pillow 和 xlrd。

```powershell
python -m pip install -r plugins/autocard/requirements.txt
node plugins/bomb-defusal/tests/test_bomb_defusal.js
python plugins/bomb-defusal/tests/test_backend.py
node --check plugins/pokemon-assistant/payload/pokemon.js
node plugins/autocard/tests/test_pokemon_native_cards.js
node plugins/autocard/tests/test_autocard_image_delivery.js
node plugins/autocard/tests/test_autocard_billing.js plugins/autocard/sealdice/一键录卡.js
Push-Location plugins/autocard
python -m unittest discover -s tests -p "test_*.py"
Pop-Location
```

测试覆盖剪线和结算去重、角色卡隔离、完整队伍导入、模板与数值解析、Rich Data 头像提取、图片消息、评分计费及服务断连恢复。输入是合成数据，HTTP 使用临时目录与本机随机端口，不访问真实玩家存档。

未打包可选第三方图标，因此相应素材测试会跳过。测试不能替代真实 QQ 权限、官方文件事件、HTTPS 图床和自编译核心的部署验收。
