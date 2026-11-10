// Embedded into index.html for Render static deployment.

  /* Ask Terp Pilot v1: transparent natural-language filtering over existing COA data. */
  const chatLog=$('#pilotChatLog'),chatInput=$('#pilotChatInput');
  const chatTerps=[
    [/limonene/i,['Limonene']],[/myrcene/i,['β-Myrcene']],
    [/\bpinene/i,['α-Pinene','β-Pinene']],
    [/linalool/i,['Linalool']],[/terpinolene/i,['Terpinolene']],
    [/caryophyllene/i,['β-Caryophyllene']],[/humulene/i,['α-Humulene']],
    [/ocimene/i,['Trans-Ocimene','Ocimene']]
  ];
  const chatVibes=[
    [/sleep|unwind|evening|night|relax/i,'unwind'],
    [/focus|bright|daytime|energ|uplift/i,'focus'],
    [/creativ|expressiv|euphor/i,'creative'],
    [/calm|mellow|grounded|anxiety/i,'calm']
  ];
  const chatAromas=[
    [/citrus|lemon|lime|orange|zest/i,'citrus'],[/pine|resinous|forest/i,'pine'],
    [/floral|rose|lavender/i,'floral'],[/pepper|spicy|spice/i,'spice'],
    [/earthy|musky|herbal/i,'earthy'],[/woody|wood/i,'wood'],
    [/fresh|eucalyptus|cool/i,'fresh']
  ];
  function chatAdd(role,html){
    const el=document.createElement('div');el.className='tp-msg tp-'+role;el.innerHTML=html;
    chatLog.appendChild(el);
    while(chatLog.children.length>24)chatLog.removeChild(chatLog.firstElementChild);
    chatLog.scrollTop=chatLog.scrollHeight;
  }
  function chatBlend(target,source){
    for(const [key,value] of Object.entries(source))target[key]=(target[key]||0)+Number(value);
  }
  function chatReset(){
    state.discovery=null;state.vibe=null;state.aromas=[];state.chat=null;state.chatPrevious=null;
    state.brand='all';state.category='all';state.query='';state.sort='name';state.visible=windowSize();
    $('#query').value='';$('#brandFilter').value='all';$('#categoryFilter').value='all';$('#sortOrder').value='name';
    chatLog.innerHTML='';chatAdd('bot','Conversation and filters cleared. What chemistry would you like to explore?');
    chatInput.value='';syncDiscoveryUI();renderExplore();
  }
  function chatReference(q){
    const m=q.match(/(?:similar to|just like|liked|loved|favorite|like)\s+(.+?)(?:\s+(?:but|with|that|and|except)\b|[,.!?]|$)/i);
    if(!m||m[1].trim().length<4)return {asked:false,record:null,name:''};
    const name=m[1].trim().toLowerCase();
    const found=PRODUCTS.filter(p=>p.name.toLowerCase().includes(name));
    found.sort((a,b)=>(b.coverage==='full')-(a.coverage==='full')||(b.date||'').localeCompare(a.date||''));
    return {asked:true,record:found[0]||null,name:m[1].trim()};
  }
  function chatCeiling(q){
    const a=q.match(/(?:under|below|less than|no more than)\s*(\d+(?:\.\d+)?)\s*%?\s*(?:of\s*)?(?:β[\s-]*)?myrcene/i);
    const b=q.match(/myrcene\s*(?:under|below|less than|<)\s*(\d+(?:\.\d+)?)\s*%?/i);
    return a||b?Number((a||b)[1]):null;
  }
  function chatCategory(q){
    if(/\b(vapes?|carts?|cartridges?|disposables?)\b/i.test(q))return 'Vape';
    if(/\b(flowers?|buds?)\b/i.test(q))return 'Flower';
    if(/\b(pre[\s-]?rolls?|joints?)\b/i.test(q))return 'Pre-roll';
    if(/\b(concentrates?|dabs?|rosin|badder|wax)\b/i.test(q))return 'Concentrate';
    return null;
  }
  function chatRun(raw){
    const q=raw.trim().slice(0,500);if(!q)return;
    chatAdd('user',esc(q));
    if(/^(clear|reset|start over|new search)\b/i.test(q)){chatReset();return}
    if(/what changed|why (?:this|that|these) (?:result|match)/i.test(q)&&state.chat){
      const first=byId.get(state.chat.lastIds?.[0]),prior=state.chatPrevious;
      let message=prior?'The previous search returned '+prior.count+' batches, compared with '+state.chat.lastCount+' now.':'The current results follow the filters above.';
      if(first)message+=' The leading batch, '+first.name+', measures '+tops(first).slice(0,3).map(([n,v])=>n+' '+num(v,2)+'%').join(', ')+'.';
      chatAdd('bot',esc(message));return;
    }
    if(/what (?:is|are)|explain|what does/i.test(q)){
      const mention=chatTerps.find(([re])=>re.test(q));
      if(mention){
        const name=mention[1][0],info=TERPENE_META[name];
        chatAdd('bot','<strong>'+esc(name)+'</strong> is a reported terpene, commonly associated with '+esc(info?.[1]||'aromatic')+' notes. Lab concentrations do not establish effects. Ask me to find batches containing it to see measured examples.');
        return;
      }
      if(/match|score/i.test(q)){chatAdd('bot','Chemistry match scores compare measured terpene patterns, not subjective effects or product quality. They are exploratory and unvalidated as predictors of experience.');return}
    }
    const follow=/^(more|less|only|instead|also|what about|but|and|with|make it|keep|remove|without)\b/i.test(q);
    const previous=follow&&state.discovery==='chat'?state.chat:null;
    const matchBrand=q.match(/\b(head change|vivid|robust)\b/i);
    const brand=matchBrand?({'head change':'Head Change',vivid:'Vivid',robust:'Robust'})[matchBrand[1].toLowerCase()]:previous?state.brand:'all';
    const category=chatCategory(q)|| (previous?state.category:'all');
    const ref=chatReference(q);
    let target=previous?Object.assign({},previous.target):{};
    const notes=[];
    if(ref.asked&&ref.record&&ref.record.coverage==='full'){
      target={};
      for(const [k,v] of tops(ref.record).slice(0,9))target[k]=v;
      notes.push('Reference fingerprint: '+ref.record.brand+' '+ref.record.name+'.');
    }else if(ref.asked)notes.push('I could not verify a matching historical batch named '+ref.name+'. I will not invent its chemistry.');
    for(const [pattern,vibe] of chatVibes)if(pattern.test(q)){
      chatBlend(target,VIBE_TARGETS[vibe]);
      notes.push('The '+vibe+' direction is a browsing label, not a proven effect.');
      break;
    }
    for(const [pattern,aroma] of chatAromas)if(pattern.test(q)){
      chatBlend(target,AROMA_TARGETS[aroma]);notes.push('Aroma direction: '+aroma+'.');
    }
    const lowerMyrcene=/(?:low|less|lower|without|no)\s+(?:β[\s-]*)?myrcene|myrcene\s+(?:low|less|lower|under|below)/i.test(q);
    for(const [re,keys] of chatTerps)if(re.test(q)&&!(lowerMyrcene&&keys.includes('β-Myrcene'))){
      for(const name of keys)target[name]=(target[name]||0)+1;
    }
    let maxMyrcene=chatCeiling(q);
    if(maxMyrcene===null)maxMyrcene=previous?previous.maxMyrcene:null;
    if(lowerMyrcene&&maxMyrcene===null)maxMyrcene=0.5;
    const m=q.match(/(?:at least|above|over|more than)\s*(\d+(?:\.\d+)?)\s*%?\s*(?:total\s*)?terp(?:enes?)?/i)||
      q.match(/(?:total\s*)?terp(?:enes?)?\s*(?:above|over|at least)\s*(\d+(?:\.\d+)?)/i);
    const minTerps=m?Number(m[1]):previous?previous.minTerps:null;
    if(!Object.keys(target).length&&brand==='all'&&category==='all'&&maxMyrcene===null&&minTerps===null){
      chatAdd('bot','I can search verified batch records by <strong>flavor direction, terpene concentrations, brand, and format.</strong> Try “piney cart with low myrcene” or “Vivid flower with at least 4% terpenes.” I cannot reliably infer gas, fruit or subjective effects from terpene panels alone.');
      return;
    }
    const last=state.chat;
    state.chatPrevious=last?{count:last.lastCount}:null;
    state.chat={target,minTerps,maxMyrcene,referenceId:ref.record?.id||previous?.referenceId||null,lastCount:0,lastIds:[]};
    state.discovery='chat';state.brand=brand;state.category=category;state.query='';state.sort='name';state.visible=20;
    $('#query').value='';$('#brandFilter').value=brand;$('#categoryFilter').value=category;$('#sortOrder').value='name';
    syncDiscoveryUI();renderExplore();
    const found=sortedFiltered(PRODUCTS);
    state.chat.lastCount=found.length;state.chat.lastIds=found.slice(0,4).map(p=>p.id);
    if(/\bgas|gassy|diesel|fuel\b/i.test(q))notes.push('Gas/fuel notes cannot be established from the terpene panel alone.');
    const conditions=[brand!=='all'?brand:null,category!=='all'?category:null,Object.keys(target).length?'terpene fingerprint':null,minTerps!==null?'≥'+num(minTerps)+'% terpenes':null,maxMyrcene!==null?'reported myrcene ≤'+num(maxMyrcene)+'%':null].filter(Boolean);
    let reply='<strong>'+found.length+' matching historical batch'+(found.length===1?'':'es')+'.</strong>';
    reply+='<span class="tp-msg-small">'+esc(conditions.join(' · '))+'</span>';
    if(notes.length)reply+='<span class="tp-msg-small">'+esc(notes.join(' '))+'</span>';
    if(!found.length)reply+='<span class="tp-msg-small">No batch meets all these conditions. Try broadening a format or chemical threshold.</span>';
    for(const p of found.slice(0,3)){
      const src=p.coa_url||(p.brand==='Head Change'?null:p.source);
      const link=/^https:\/\//.test(src||'')?'<a target="_blank" rel="noopener noreferrer" href="'+esc(src)+'">Original COA ↗</a>':'No indexed COA PDF';
      const similarity=Object.keys(target).length?' · '+profileScore(p)+'% chemical profile fit':'';
      reply+='<div class="tp-chat-hit"><button type="button" data-open="'+p.id+'">'+esc(p.brand+' · '+p.name)+'</button><small>'+esc(p.category)+' · '+(p.total==null?'Total terpenes not reported':num(p.total)+'% total terpenes')+esc(similarity)+'<br>'+tops(p).slice(0,3).map(([n,v])=>esc(n)+' '+num(v,2)+'%').join(' · ')+'<br>'+link+'</small></div>';
    }
    reply+='<span class="tp-msg-small">Measured chemistry, not a prediction of effects, safety, quality, or current stock. The catalog below uses these same filters. You can refine either way.</span>';
    chatAdd('bot',reply);
  }
  $('#pilotChatForm').addEventListener('submit',event=>{event.preventDefault();const q=chatInput.value;chatInput.value='';chatRun(q)});
  chatInput.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('#pilotChatForm').requestSubmit()}});
  for(const btn of document.querySelectorAll('[data-chat-prompt]'))btn.addEventListener('click',()=>chatRun(btn.dataset.chatPrompt));
  $('#pilotChatReset').addEventListener('click',chatReset);
