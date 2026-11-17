"""本地业务页面交互。"""

def detail_fragment(item):
    return '<select id="tier"><option>月卡</option><option>季度卡</option></select><button id="rights">查看权益</button><output id="rights-text"></output><script>document.querySelector(\'#rights\').onclick=()=>document.querySelector(\'#rights-text\').textContent=document.querySelector(\'#tier\').value+\'：权益说明\';document.querySelector(\'#tier\').onchange=()=>document.querySelector(\'#rights-text\').textContent=\'\';</script>'
