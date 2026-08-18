window.MobileData = (() => {
  const sources = [
    {key:'mymobile', name:'MyMobile', host:'mymobile.pk', status:'Healthy', rate:97.8, latency:620, records:2148, queue:1, color:'#09855b'},
    {key:'daraz', name:'Daraz', host:'daraz.pk', status:'Healthy', rate:95.1, latency:890, records:3892, queue:2, color:'#ff9100'},
    {key:'gsmarena', name:'GSMArena', host:'gsmarena.com', status:'Rate limited', rate:83.2, latency:1630, records:7215, queue:7, color:'#5c8bc0'},
    {key:'mega', name:'Mega.pk', host:'mega.pk', status:'Healthy', rate:96.4, latency:710, records:1846, queue:0, color:'#2e1b41'},
    {key:'whatamobile', name:'WhataMobile', host:'whatamobile.com.pk', status:'Degraded', rate:89.6, latency:1280, records:1297, queue:4, color:'#b85b7c'},
    {key:'whatmobile', name:'WhatMobile', host:'whatmobile.com.pk', status:'Healthy', rate:94.7, latency:780, records:2674, queue:1, color:'#41a883'}
  ];
  const devices = [
    {id:'DEV-10284',brand:'Samsung',model:'Galaxy S26 Ultra',price:424999,offers:18,source:'GSMArena',completeness:99,status:'Verified',updated:'2 min ago'},
    {id:'DEV-10283',brand:'Apple',model:'iPhone 17 Pro Max',price:519999,offers:24,source:'Daraz',completeness:97,status:'Verified',updated:'7 min ago'},
    {id:'DEV-10282',brand:'Xiaomi',model:'15 Ultra',price:289999,offers:31,source:'WhatMobile',completeness:96,status:'Review',updated:'12 min ago'},
    {id:'DEV-10281',brand:'Infinix',model:'Note 50 Pro+',price:129999,offers:15,source:'Mega.pk',completeness:94,status:'Verified',updated:'18 min ago'},
    {id:'DEV-10280',brand:'Oppo',model:'Find X9 Pro',price:349999,offers:13,source:'MyMobile',completeness:92,status:'Review',updated:'24 min ago'},
    {id:'DEV-10279',brand:'Vivo',model:'X300 Pro',price:334999,offers:11,source:'WhataMobile',completeness:91,status:'Verified',updated:'31 min ago'},
    {id:'DEV-10278',brand:'Samsung',model:'Galaxy A57',price:144999,offers:42,source:'Daraz',completeness:98,status:'Verified',updated:'38 min ago'},
    {id:'DEV-10277',brand:'Tecno',model:'Camon 50 Premier',price:119999,offers:19,source:'WhatMobile',completeness:89,status:'Partial',updated:'44 min ago'}
  ];
  const offers = devices.map((d,i)=>({id:`OFF-${8801-i}`,device:d.model,retailer:['Daraz','Mega.pk','PriceOye'][i%3],price:d.price-(i%3)*4500,stock:i%4?'In stock':'Low stock',source:d.source,updated:d.updated}));
  const runs = sources.map((s,i)=>({id:`RUN-${58421-i}`,source:s.name,scope:i===2?'Full catalogue':'Pages 1–15',records:320+i*77,status:s.status==='Healthy'?'Completed':'Partial',duration:`${12+i*3}m`,started:`0${i+1}:2${i}`}));
  const events = [
    ['Price drop','Galaxy S26 Ultra decreased by PKR 8,500','Daraz','now'],
    ['New listing','iPhone 17 Air added to catalogue','GSMArena','18s'],
    ['Record updated','Xiaomi 15 Ultra availability changed','WhatMobile','42s'],
    ['Quality alert','Seven records missing chipset values','WhataMobile','1m'],
    ['Run complete','312 normalized offers stored','MyMobile','2m'],
    ['Rate limit','Backoff applied for 120 seconds','GSMArena','3m']
  ];
  return {sources,devices,offers,runs,events,
    growth:[11140,11480,11710,11960,12340,12720,13110,13680,14120,14590,15020,15284],
    offersTrend:[35100,36400,37200,38600,39750,41100,42900,44300,45500,46900,48120,48921],
    brands:[{name:'Samsung',value:31},{name:'Xiaomi',value:24},{name:'Apple',value:17},{name:'Infinix',value:12},{name:'Oppo',value:9},{name:'Other',value:7}]
  };
})();
