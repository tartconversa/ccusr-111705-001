"""本地业务页面交互。"""

def detail_fragment(item):
    return "<select id=\"tier\"><option>月卡</option><option>季度卡</option></select><button id=\"rights\">查看权益</button><output id=\"rights-text\"></output><button id=\"expire\">模拟活动失效</button><script>let tier=document.querySelector('#tier'),rights=document.querySelector('#rights-text');let prices={月卡:'99 元',季度卡:'279 元'};let expired=false;tier.onchange=()=>{rights.textContent='';document.querySelector('#result').textContent='';document.querySelector('#summary').textContent=tier.value+' · '+prices[tier.value]};document.querySelector('#rights').onclick=()=>rights.textContent=tier.value+'：'+(expired?'活动已失效':'权益说明');document.querySelector('#preview').onclick=()=>{document.querySelector('#result').textContent=tier.value+'：'+(expired?'活动已失效':prices[tier.value])};document.querySelector('#expire').onclick=()=>{expired=true;rights.textContent='';document.querySelector('#result').textContent=''};</script>"

def source_extension(item):
    return """<output id="offer-revision" data-revision="1">版本 1</output><output id="rights-revision"></output><output id="checkout-revision"></output><script>(()=>{
let offer=document.querySelector('#offer-revision'), rights=document.querySelector('#rights-revision'), checkout=document.querySelector('#checkout-revision');
let revision=1;const current=()=>({tier:document.querySelector('#tier').value,revision});
document.querySelector('#tier').addEventListener('change',()=>{revision++;offer.dataset.revision=String(revision);offer.textContent='版本 '+revision;rights.textContent='';checkout.textContent='';});
document.querySelector('#rights').addEventListener('click',()=>{let viewed=current();rights.textContent='权益读取中';setTimeout(()=>{rights.textContent=viewed.tier+'：权益版本 '+viewed.revision;},80)});
document.querySelector('#preview').addEventListener('click',()=>{let viewed=current();checkout.textContent='结算读取中';setTimeout(()=>{checkout.textContent=viewed.tier+'：'+(offer.dataset.expired==='true'?'活动已失效':'结算版本 '+viewed.revision);},65)});
document.querySelector('#expire').addEventListener('click',()=>{revision++;offer.dataset.revision=String(revision);offer.dataset.expired='true';offer.textContent='活动失效 / 版本 '+revision;rights.textContent='';checkout.textContent='';});
})();</script>"""
