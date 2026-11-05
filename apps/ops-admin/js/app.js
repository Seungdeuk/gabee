/* 운영 관리자 화면. 서버 모드(기본)는 실서버 값을, 로컬 샘플 모드는 가짜 값을 보여 준다. 서버에서 받은 값은 반드시 esc() 로 감싼다. */
import { config } from "./config.js";
import { request, setToken, setUnauthorizedHandler } from "./api.js";
import { login as apiLogin, logout as apiLogout } from "./auth.js";

(function(){
'use strict';
var LIVE=!config.sampleMode;
var $=function(s){return document.querySelector(s)};
var esc=function(s){return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})};
var fmt=function(n){return Math.round(n).toLocaleString('ko-KR')};
var pad=function(n){return String(n).padStart(2,'0')};
function rnd(seed){return function(){seed=(seed*16807)%2147483647;return (seed-1)/2147483646}}

/* ---------- icons ---------- */
var IC={
 dash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
 infra:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></svg>',
 api:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M8 7 3 12l5 5M16 7l5 5-5 5M14 4l-4 16"/></svg>',
 logs:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4h14v16H5zM9 9h6M9 13h6M9 17h3"/></svg>',
 deploy:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
 bell:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 17V11a6 6 0 1 1 12 0v6l1.5 2h-15zM10 21h4"/></svg>',
 refresh:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
 menu:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
 ok:'<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="m2.5 6.3 2.4 2.4 4.6-5"/></svg>',
 warn:'<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2.5v4.2M6 9.2v.1"/></svg>',
 err:'<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="m3 3 6 6M9 3 3 9"/></svg>',
 info:'<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 5.4v3.6M6 2.8v.1"/></svg>',
 empty:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 7l2-3h14l2 3v12H3zM3 7h6l1 2h4l1-2h6"/></svg>',
 fail:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.1"/></svg>',
 cloud:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9.5 4.3 4.3 0 0 1 17.5 18z"/></svg>'
};

/* ---------- sample data (not real operating data) ---------- */
var NOW=new Date();
var HOURS=[];for(var h=23;h>=0;h--){var d=new Date(NOW.getTime()-h*3600000);HOURS.push(pad(d.getHours())+':00')}
var REQ=[312,268,231,205,198,224,310,452,688,812,934,1021,988,947,903,876,921,1004,1130,1186,1098,942,712,486];
var FAIL=[4,3,2,2,1,3,5,6,9,11,14,31,18,12,10,9,13,15,22,19,14,11,8,5];
function wave(base,amp,seed,n){var r=rnd(seed),out=[];for(var i=0;i<(n||24);i++){out.push(Math.max(1,base+(r()-.5)*amp+Math.sin(i/3.2)*amp*.25))}return out}

var SERVICES=[
 {id:'cf',name:'Cloudflare Workers',st:'ok',desc:'엣지 라우팅 정상 동작 중',req:21430,err:38,avg:28,spark:wave(28,10,11)},
 {id:'run',name:'Cloud Run',st:'warn',desc:'새 인스턴스 첫 요청 지연 감지 (모델 로드)',req:18902,err:164,avg:312,spark:wave(310,260,23)},
 {id:'api',name:'FastAPI',st:'ok',desc:'API 서버 응답 정상',req:18902,err:92,avg:244,spark:wave(240,90,31)},
 {id:'sb',name:'Supabase / PostgreSQL',st:'ok',desc:'DB 연결 및 쿼리 정상',req:41200,err:3,avg:18,spark:wave(18,8,47)},
 {id:'cl',name:'Claude API',st:'ok',desc:'일부 요청 한도(429) 재시도 발생',req:9120,err:41,avg:1820,spark:wave(1800,700,59)}
];
var APIS=[
 ['Cloudflare Workers','/edge/*','ok',28,21430,.18,3],
 ['FastAPI','/health','ok',9,8640,0,1],
 ['FastAPI','/api/chat','warn',2140,6210,1.9,2],
 ['FastAPI','/api/schedules','ok',112,3980,.6,2],
 ['FastAPI','/api/care','ok',98,2140,.3,2],
 ['FastAPI','/api/settlements','ok',134,1520,.5,2],
 ['FastAPI','/api/files/upload','err',48200,412,6.8,1],
 ['Supabase','PostgreSQL (pooler)','ok',18,41200,.01,1],
 ['Supabase','pgvector 검색','warn',420,1630,.4,3],
 ['Claude API','/v1/messages','ok',1820,9120,.45,2]
];
var T=[
 ['TIMEOUT','ERROR','Cloud Run','/api/files/upload',504,'OCR 모델 로드 대기 중 요청 시간 초과 (콜드 스타트 의심)'],
 ['RATE_LIMIT','WARNING','Claude API','/v1/messages',429,'요청 한도 초과로 재시도 발생'],
 ['DB_CONN','ERROR','Supabase','PostgreSQL (pooler)',503,'커넥션 풀 포화로 신규 연결 대기 시간 초과'],
 ['UNHANDLED','CRITICAL','FastAPI','/api/chat',500,'AI 채팅 응답 생성 중 처리되지 않은 예외'],
 ['VALIDATION','INFO','FastAPI','/api/schedules',422,'일정 등록 요청 본문 검증 실패'],
 ['UPSTREAM','ERROR','Cloudflare Workers','/edge/*',502,'오리진(Cloud Run) 응답 지연으로 게이트웨이 오류'],
 ['SLOW_QUERY','WARNING','Supabase','pgvector 검색',200,'벡터 검색 쿼리가 1.2초를 초과'],
 ['AUTH','WARNING','FastAPI','/api/care',401,'만료된 토큰으로 접근 시도'],
 ['TIMEOUT','ERROR','Claude API','/v1/messages',504,'모델 응답 대기 시간 초과'],
 ['UNHANDLED','ERROR','FastAPI','/api/settlements',500,'정산 합계 계산 중 예외 발생']
];
var ACT={'미처리':'','확인 중':'원인 확인 중. 같은 시간대 배포 이력과 Cloud Run 로그를 대조하고 있음.','해결':'재시도 로직 조정 후 재발 없음 확인.'};
var LOGS=(function(){var r=rnd(7),out=[],ago=6;
 for(var i=0;i<28;i++){var t=T[(i*7+(i%3))%10];
  ago+= i<12 ? 60+Math.floor(r()*80) : 240+Math.floor(r()*500);
  var st=i<6?'미처리':(i<12?(i%2?'확인 중':'미처리'):(i%4===0?'확인 중':'해결'));
  var id='tr-'+Math.floor(r()*0xffffff).toString(16).padStart(6,'0')+Math.floor(r()*0xffff).toString(16).padStart(4,'0');
  out.push({i:i,ago:ago,type:t[0],sev:t[1],svc:t[2],path:t[3],code:t[4],msg:t[5],proc:st,trace:id});}
 return out})();
var DEPLOYS=[
 ['v1.4.2',30,'prod','github-actions','성공','3분 12초','a91f3c2','이미지 교체: 일정 등록 입력 단계 단순화'],
 ['v1.4.1',1500,'prod','github-actions','실패','1분 48초','5be07d1','헬스체크 실패로 중단. 직전 revision 유지'],
 ['v1.4.1-dev',1620,'dev','github-actions','성공','3분 02초','5be07d1','dev 환경 검증용 배포'],
 ['v1.4.0',4300,'prod','수동 배포','성공','6분 40초','c20d88e','OCR/NER 모델 로드 방식 변경'],
 ['v1.3.9',7200,'prod','github-actions','성공','3분 25초','77ab1e0','정산 계산 오류 수정'],
 ['v1.3.8',10100,'prod','github-actions','성공','3분 09초','0f4e9b6','AI 채팅 응답 타임아웃 상향'],
 ['v1.3.7',14400,'prod','수동 배포','실패','2분 11초','e8c5a43','환경변수 누락으로 기동 실패'],
 ['v1.3.6',18000,'prod','github-actions','성공','3분 18초','3d2b710','돌봄 기록 목록 페이징 추가'],
 ['v1.3.5',26000,'dev','github-actions','성공','3분 01초','b61a2f9','dev 환경 검증용 배포'],
 ['v1.3.4',32000,'prod','수동 배포','성공','7분 05초','19cc7ae','초기 운영 배포']
].map(function(a,i){return {i:i,ver:a[0],ago:a[1],env:a[2],by:a[3],res:a[4],dur:a[5],sha:a[6],note:a[7]}});

var ALERTS=[
 {i:0,sev:'CRITICAL',t:'/api/chat 처리되지 않은 예외가 반복 발생',ago:42,read:false},
 {i:1,sev:'WARNING',t:'Claude API 429 재시도 증가',ago:95,read:false},
 {i:2,sev:'ERROR',t:'v1.4.1 배포 헬스체크 실패, 직전 revision 유지',ago:1500,read:false},
 {i:3,sev:'WARNING',t:'Cloud Run 새 인스턴스 첫 요청 지연 52초',ago:210,read:true},
 {i:4,sev:'INFO',t:'v1.4.2 배포 완료',ago:30,read:true}
];
var PREV=(function(){var a=REQ.map(function(v,i){return v*(0.9+((i*37)%11)/55)});var k=(REQ.reduce(function(x,y){return x+y},0)/1.082)/a.reduce(function(x,y){return x+y},0);return a.map(function(v){return Math.round(v*k)})})();

/* ---------- state ---------- */
var PAGES=[
 {id:'dashboard',label:'운영 대시보드',ic:'dash',desc:'전체 시스템 상태와 최근 이슈를 한 화면에서 확인합니다.'},
 {id:'infra',label:'인프라 모니터링',ic:'infra',desc:'Cloudflare, Cloud Run, FastAPI, Supabase의 상태를 서비스별로 확인합니다.'},
 {id:'api',label:'API 상태 관리',ic:'api',desc:'주요 API와 외부 서비스의 응답 시간과 오류율을 확인합니다.'},
 {id:'logs',label:'로그 및 오류 관리',ic:'logs',desc:'서버와 API에서 발생한 오류를 검색하고 처리 상태를 확인합니다.'},
 {id:'deploy',label:'배포 및 DB 관리',ic:'deploy',desc:'배포 이력과 DB 상태를 조회합니다. 데이터 수정 기능은 없습니다.'}
];
var S={auth:false,sort:{},page:'dashboard',view:'ok',range:'24h',from:'',to:'',svcFilter:'전체',lf:{type:'',sev:'',path:'',code:'',proc:'',q:''},lp:1,dp:1,modal:null,updated:new Date(),notif:false};
var RANGE_F={'1h':.045,'24h':1,'7d':6.4,'30d':26,'custom':1};
var RANGE_L={'1h':'최근 1시간','24h':'최근 24시간','7d':'최근 7일','30d':'최근 30일','custom':'직접 선택'};

/* ---------- helpers ---------- */
function unread(){return ALERTS.filter(function(a){return !a.read}).length}
function alertItems(){return ALERTS.map(function(a){return '<div class="it" data-act="readAlert" data-id="'+a.i+'" style="cursor:pointer;'+(a.read?'opacity:.6':'')+'">'+sevBadge(a.sev)+'<div>'+esc(a.t)+'<small>'+when(a.ago)+(a.read?' · 확인함':'')+'</small></div></div>'}).join('')}
function when(ago){var d=new Date(NOW.getTime()-ago*60000);return pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes())}
function stateLbl(k){return {ok:'정상',warn:'주의',err:'오류',info:'정보'}[k]}
function badge(k,label){return '<span class="badge '+k+'">'+(IC[k]||'')+esc(label||stateLbl(k))+'</span>'}
function sevBadge(s){var m={INFO:'info',WARNING:'warn',ERROR:'err',CRITICAL:'crit'};return '<span class="badge '+m[s]+'">'+(s==='CRITICAL'?IC.err:IC[m[s]])+s+'</span>'}
function procBadge(p){var m={'미처리':'err','확인 중':'warn','해결':'ok'};return badge(m[p],p)}
function resBadge(r){return r==='성공'?badge('ok','성공'):badge('err','실패')}
function ms(v){return v>=1000?(v/1000).toFixed(1)+'초':fmt(v)+'ms'}
function deltaHtml(v,goodWhenDown){var cls=Math.abs(v)<.5?'flat':((v<0)===!!goodWhenDown?'good':'bad');return '<span class="delta '+cls+'">'+(v>0?'▲ ':v<0?'▼ ':'')+Math.abs(v).toFixed(1)+'%</span>'}
function sum(a){return a.reduce(function(x,y){return x+y},0)}
function f(){return RANGE_F[S.range]}
function sparkline(vals,st){var w=120,h=30,mx=Math.max.apply(null,vals),mn=Math.min.apply(null,vals),sp=(mx-mn)||1;
 var pts=vals.map(function(v,i){return (i*(w-4)/(vals.length-1)+2).toFixed(1)+','+(h-3-(v-mn)/sp*(h-6)).toFixed(1)}).join(' ');
 var last=pts.split(' ').pop().split(',');
 return '<svg viewBox="0 0 '+w+' '+h+'" width="120" height="30" aria-hidden="true"><polyline points="'+pts+'" fill="none" style="stroke:var(--'+(st==='ok'?'accent':st)+')" stroke-width="1.6"/><circle cx="'+last[0]+'" cy="'+last[1]+'" r="2.6" style="fill:var(--'+(st==='ok'?'accent':st)+')"/></svg>'}

/* ---------- state wrappers: loading / error / empty ---------- */
function guard(kind,fn){
 if(S.view==='loading')return '<div style="padding:16px;display:flex;flex-direction:column;gap:10px"><div class="sk" style="height:'+(kind==='chart'?170:kind==='card'?26:14)+'px"></div><div class="sk" style="height:14px;width:70%"></div><div class="sk" style="height:14px;width:45%"></div></div>';
 if(S.view==='error')return '<div class="state err">'+IC.fail+'<b>데이터를 불러오지 못했습니다</b><span>수집기 응답이 없습니다. 잠시 후 다시 시도하세요.</span><button class="btn" data-act="retry">다시 시도</button></div>';
 if(S.view==='empty')return '<div class="state">'+IC.empty+'<b>표시할 데이터가 없습니다</b><span>선택한 기간에 수집된 기록이 없습니다. 기간을 넓혀 보세요.</span></div>';
 return fn()}
function panelFixed(title,sub,body,extra){return '<section class="panel"><header><div><h2>'+title+'</h2>'+(sub?'<small>'+sub+'</small>':'')+'</div>'+(extra||'')+'</header>'+body+'</section>'}

/* ---------- components ---------- */
function Sidebar(){$('#nav').innerHTML=PAGES.map(function(p){return '<button data-act="nav" data-id="'+p.id+'"'+(S.page===p.id?' aria-current="page"':'')+'>'+IC[p.ic]+'<span>'+p.label+'</span></button>'}).join('')}
function Header(){var p=PAGES.filter(function(x){return x.id===S.page})[0];
 var u=S.updated;
 $('#hdr').innerHTML='<button class="ibtn menu-btn" data-act="openMenu" aria-label="메뉴 열기">'+IC.menu+'</button>'+
  '<div class="hdr-t"><h1>'+p.label+'</h1><p>'+p.desc+'</p></div>'+
  '<div class="hdr-r"><span class="upd">마지막 갱신 '+pad(u.getHours())+':'+pad(u.getMinutes())+':'+pad(u.getSeconds())+'</span>'+
  '<button class="ibtn" data-act="refresh">'+IC.refresh+'새로고침</button>'+
  (LIVE?'':'<div class="pwrap"><button class="ibtn" data-act="notif" aria-label="알림 '+unread()+'건" aria-expanded="'+S.notif+'">'+IC.bell+(unread()?'<span class="dot"></span>':'')+'</button>'+
  (S.notif?'<div class="pop"><h4>최근 알림 (샘플) · 클릭하면 확인 처리</h4>'+alertItems()+
         '</div>':'')+'</div>')+
  '<div class="me"><div class="avatar">운</div><div><strong style="font-weight:500">운영 담당자</strong></div></div></div>'}
function SampleBar(){return '<div class="sample"><span><strong>샘플 데이터</strong> 이 화면의 모든 수치는 UI 확인용 예시이며 실제 운영 데이터가 아닙니다.</span>'+
 '<span class="toolbar" style="gap:8px"><span>상태 미리보기</span>'+Seg('view',[['ok','정상'],['loading','로딩'],['error','오류'],['empty','데이터 없음']],S.view)+'</span></div>'}
function Seg(key,items,cur){return '<span class="seg" role="group">'+items.map(function(i){return '<button data-act="seg" data-k="'+key+'" data-v="'+i[0]+'" aria-pressed="'+(cur===i[0])+'">'+i[1]+'</button>'}).join('')+'</span>'}
function DateRangePicker(){return '<div class="drp">'+Seg('range',[['1h','1시간'],['24h','24시간'],['7d','7일'],['30d','30일'],['custom','직접 선택']],S.range)+
 (S.range==='custom'?'<input type="date" id="dFrom" value="'+S.from+'" aria-label="시작일"><span>~</span><input type="date" id="dTo" value="'+S.to+'" aria-label="종료일">':'')+'</div>'}
function SummaryCard(o){return '<div class="sc"><div class="lbl"><span>'+o.label+'</span>'+(o.badge||'')+'</div>'+
 guard('card',function(){return '<div class="val num">'+o.value+(o.unit?'<small>'+o.unit+'</small>':'')+'</div><div class="sub">'+o.sub+'</div>'})+'</div>'}
function ServiceStatusCard(s,clickable){var inner='<div class="ic '+s.st+'">'+IC.cloud+'</div><div class="tx"><b>'+s.name+'</b><span>'+s.desc+'</span></div>'+badge(s.st);
 return clickable?'<button class="svc" data-act="svcModal" data-id="'+s.id+'">'+inner+'</button>':'<div class="svc">'+inner+'</div>'}
function MonitoringChart(o){
 var W=640,H=o.h||210,pl=46,pr=10,pt=10,pb=24,n=o.labels.length;
 var all=o.type==='bar'?o.a.map(function(v,i){return v+o.b[i]}):o.series.reduce(function(x,s){return x.concat(s.values)},[]);
 var mx=Math.max.apply(null,all)*1.08,p=Math.pow(10,Math.floor(Math.log10(mx)));
 mx=[1,1.5,2,2.5,3,4,5,6,8,10].filter(function(x){return x*p>=mx})[0]*p;
 var X=function(i){return pl+(i+.5)*(W-pl-pr)/n},Y=function(v){return pt+(1-v/mx)*(H-pt-pb)};
 var g='',i;
 for(i=0;i<=4;i++){var v=mx*i/4,y=Y(v);g+='<line x1="'+pl+'" x2="'+(W-pr)+'" y1="'+y+'" y2="'+y+'" style="stroke:var(--grid)"/><text x="'+(pl-6)+'" y="'+(y+4)+'" text-anchor="end">'+(o.fy?o.fy(v):fmt(v))+'</text>'}
 var step=Math.ceil(n/6);
 for(i=0;i<n;i+=step)g+='<text x="'+X(i)+'" y="'+(H-6)+'" text-anchor="middle">'+o.labels[i]+'</text>';
 var body='';
 if(o.type==='bar'){var bw=Math.max(3,(W-pl-pr)/n*.62);
  for(i=0;i<n;i++){var yo=Y(o.a[i]),yt=Y(o.a[i]+o.b[i]),base=Y(0),fh=Math.max(2,yo-yt);
   body+='<g class="bar" data-i="'+i+'"><rect x="'+(X(i)-(W-pl-pr)/n/2)+'" y="'+pt+'" width="'+((W-pl-pr)/n)+'" height="'+(H-pt-pb)+'" fill="transparent"/>'+
    '<rect x="'+(X(i)-bw/2)+'" y="'+yo+'" width="'+bw+'" height="'+(base-yo)+'" rx="1.5" style="fill:var(--bar)"/>'+
    '<rect x="'+(X(i)-bw/2)+'" y="'+(yo-fh)+'" width="'+bw+'" height="'+fh+'" rx="1.5" style="fill:var(--err)"/></g>'}}
 else{o.series.forEach(function(s,si){var pts=s.values.map(function(v,j){return X(j).toFixed(1)+','+Y(v).toFixed(1)});
   if(si===0&&o.area)body+='<polygon points="'+X(0)+','+Y(0)+' '+pts.join(' ')+' '+X(n-1)+','+Y(0)+'" style="fill:var(--'+s.c+');opacity:.12"/>';
   body+='<polyline points="'+pts.join(' ')+'" fill="none" stroke-width="2" stroke-linejoin="round"'+(s.d?' stroke-dasharray="5 4"':'')+' style="stroke:var(--'+s.c+')"/>';
   if(!s.d){var lp=pts[n-1].split(',');body+='<circle cx="'+lp[0]+'" cy="'+lp[1]+'" r="3.5" style="fill:var(--'+s.c+')"/>'}})}
 var id=o.id||'ch',lbl=o.aria||'시간별 추이 차트';
 return '<svg class="chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+lbl+'" data-chart="'+id+'">'+g+body+'</svg>'}
function sortRows(tid,cols,rows){var s=S.sort[tid];if(!s||!cols[s.c]||!cols[s.c].k)return rows;var k=cols[s.c].k;return rows.slice().sort(function(a,b){var x=k(a),y=k(b);return (x<y?-1:x>y?1:0)*s.d})}
function DataTable(cols,rows,rowAct,tid){
 if(!rows.length)return '<div class="state">'+IC.empty+'<b>조건에 맞는 항목이 없습니다</b><span>필터를 조정해 보세요.</span></div>';
 return '<div class="tw"><table><thead><tr>'+cols.map(function(c,ci){var so=tid&&S.sort[tid]&&S.sort[tid].c===ci?S.sort[tid].d:0;return '<th class="'+(c.r?'r':'')+'"'+(c.k&&tid?' aria-sort="'+(so===1?'ascending':so===-1?'descending':'none')+'"':'')+'>'+(c.k&&tid?'<button class="lnk" style="color:inherit;text-decoration:none;font-weight:500" data-act="sort" data-t="'+tid+'" data-c="'+ci+'">'+c.h+' <span aria-hidden="true">'+(so===1?'▲':so===-1?'▼':'↕')+'</span></button>':c.h)+'</th>'}).join('')+'</tr></thead><tbody>'+
 rows.map(function(r){return '<tr'+(rowAct?' class="click" tabindex="0" data-act="'+rowAct+'" data-id="'+(r.i!==undefined?r.i:r.key)+'"':'')+'>'+cols.map(function(c){return '<td class="'+(c.r?'r num':'')+'">'+c.f(r)+'</td>'}).join('')+'</tr>'}).join('')+'</tbody></table></div>'}
function Pagination(total,page,size,key){var pages=Math.max(1,Math.ceil(total/size)),b='';
 for(var i=1;i<=pages;i++)b+='<button data-act="page" data-k="'+key+'" data-v="'+i+'"'+(i===page?' aria-current="true"':'')+'>'+i+'</button>';
 return '<div class="pager"><span>총 '+fmt(total)+'건 · '+page+' / '+pages+' 페이지</span><div class="pg"><button data-act="page" data-k="'+key+'" data-v="'+(page-1)+'"'+(page<=1?' disabled':'')+' aria-label="이전">‹</button>'+b+'<button data-act="page" data-k="'+key+'" data-v="'+(page+1)+'"'+(page>=pages?' disabled':'')+' aria-label="다음">›</button></div></div>'}
function opts(list,cur){return '<option value="">전체</option>'+list.map(function(x){return '<option'+(String(cur)===String(x)?' selected':'')+'>'+x+'</option>'}).join('')}
function SearchFilter(){var l=S.lf;
 return '<div class="pbody"><div class="filters">'+
 '<div class="field"><label for="f-q">검색</label><input id="f-q" type="search" placeholder="메시지 · Trace ID" value="'+esc(l.q)+'"></div>'+
 '<div class="field"><label for="f-type">오류 유형</label><select id="f-type" data-f="type">'+opts(['TIMEOUT','RATE_LIMIT','DB_CONN','UNHANDLED','VALIDATION','UPSTREAM','SLOW_QUERY','AUTH'],l.type)+'</select></div>'+
 '<div class="field"><label for="f-sev">심각도</label><select id="f-sev" data-f="sev">'+opts(['INFO','WARNING','ERROR','CRITICAL'],l.sev)+'</select></div>'+
 '<div class="field"><label for="f-path">API Endpoint</label><select id="f-path" data-f="path">'+opts(['/api/chat','/api/schedules','/api/care','/api/settlements','/api/files/upload','/edge/*','/v1/messages','PostgreSQL (pooler)','pgvector 검색'],l.path)+'</select></div>'+
 '<div class="field"><label for="f-code">상태 코드</label><select id="f-code" data-f="code">'+opts([200,401,422,429,500,502,503,504],l.code)+'</select></div>'+
 '<div class="field"><label for="f-proc">처리 상태</label><select id="f-proc" data-f="proc">'+opts(['미처리','확인 중','해결'],l.proc)+'</select></div>'+
 '<div class="field"><button class="btn" data-act="resetF" style="width:100%">필터 초기화</button></div></div></div>'}

/* ---------- pages ---------- */
function recentLogs(){return LOGS.filter(function(l){return l.ago<=1440})}
function pageDashboard(){
 var tot=sum(REQ),fl=sum(FAIL),rl=recentLogs(),sv={CRITICAL:0,ERROR:0,WARNING:0};
 rl.forEach(function(l){if(sv[l.sev]!==undefined)sv[l.sev]++});
 var avg=SERVICES[2].avg+42;
 var cards='<div class="grid4">'+
  SummaryCard({label:'전체 시스템 상태',badge:badge('warn'),value:'주의',sub:'<span>운영 중인 서비스 <b>4</b>개</span><span class="chip">정상 3</span><span class="chip">주의 1</span><span class="chip">장애 0</span>'})+
  SummaryCard({label:'API 요청 현황 (24시간)',value:fmt(tot),unit:'건',sub:'<span>이전 24시간 대비 '+deltaHtml(8.2)+'</span>'})+
  SummaryCard({label:'오류 발생 현황 (24시간)',value:fmt(fl),unit:'건',sub:'<span>미처리 <b>'+LOGS.filter(function(l){return l.proc==="미처리"}).length+'</b>건</span><span class="chip">CRITICAL '+sv.CRITICAL+'</span><span class="chip">ERROR '+sv.ERROR+'</span><span class="chip">WARNING '+sv.WARNING+'</span>'})+
  SummaryCard({label:'평균 API 응답 시간',value:fmt(avg),unit:'ms',sub:'<span>이전 24시간 대비 '+deltaHtml(12.4,true)+'</span>'})+'</div>';
 var trend=panelFixed('시간별 API 요청 추이','최근 24시간 · 이전 24시간과 비교',
  '<div class="pbody">'+guard('chart',function(){return '<div class="legend" style="margin-bottom:8px"><span><i style="background:var(--accent)"></i>최근 24시간 '+fmt(tot)+'건</span><span><i style="background:var(--muted)"></i>이전 24시간 '+fmt(sum(PREV))+'건</span></div>'+MonitoringChart({type:'line',labels:HOURS,series:[{values:REQ,c:'accent'},{values:PREV,c:'muted',d:1}],area:1,h:200,id:'tr',aria:'시간별 API 요청 추이 선 차트'})})+'</div>');
 var chart=panelFixed('정상 요청과 실패 요청 비교','최근 24시간 · 막대에 마우스를 올리면 값을 볼 수 있습니다',
  '<div class="pbody">'+guard('chart',function(){return '<div class="toolbar" style="margin-bottom:8px"><div class="legend"><span><i style="background:var(--bar)"></i>정상 '+fmt(tot-fl)+'</span><span><i style="background:var(--err)"></i>실패 '+fmt(fl)+' ('+(fl/tot*100).toFixed(2)+'%)</span></div><div class="readout" id="readout-ch">막대에 마우스를 올리면 시간별 값을 볼 수 있습니다.</div></div>'+
  MonitoringChart({type:'bar',labels:HOURS,a:REQ.map(function(v,i){return v-FAIL[i]}),b:FAIL,id:'ch',aria:'시간별 정상 요청과 실패 요청 막대 차트'})})+'</div>');
 var svc=panelFixed('서비스별 상태','상태 클릭 시 인프라 모니터링에서 상세 확인',guard('card',function(){return ['cf','run','sb','cl'].map(function(id){var s=SERVICES.filter(function(x){return x.id===id})[0];if(id==='run')s=Object.assign({},s,{name:'Cloud Run / FastAPI'});return ServiceStatusCard(s,true)}).join('')}).replace(/^(<div style="padding)/,'$1'));
 var errCols=[{h:'발생 시간',f:function(l){return '<span class="mono">'+when(l.ago)+'</span>'}},{h:'오류 유형',f:function(l){return esc(l.type)}},{h:'API 경로',f:function(l){return '<span class="mono">'+esc(l.path)+'</span>'}},{h:'상태 코드',r:1,f:function(l){return l.code}},{h:'처리 상태',f:function(l){return procBadge(l.proc)}}];
 var errs=panelFixed('최근 오류 발생 내역','최근 6건',guard('table',function(){return '<div class="pbody flush">'+DataTable(errCols,LOGS.slice(0,6),'logModal')+'</div>'}),'<button class="lnk" data-act="nav" data-id="logs">전체 보기</button>');
 var dep=panelFixed('최근 배포 이력','최근 5건',guard('table',function(){return '<div class="pbody flush">'+DEPLOYS.slice(0,5).map(function(d){return '<button class="svc" data-act="depModal" data-id="'+d.i+'"><div class="tx"><b class="mono" style="font-family:var(--mono)">'+d.ver+'</b><span>'+when(d.ago)+' · '+d.env+'</span></div>'+resBadge(d.res)+'</button>'}).join('')+'</div>'}),'<button class="lnk" data-act="nav" data-id="deploy">전체 보기</button>');
 var alerts=panelFixed('주요 시스템 알림','클릭하면 확인 처리됩니다',guard('card',function(){return '<div class="pbody flush">'+ALERTS.slice(0,4).map(function(a){return '<button class="svc" data-act="readAlert" data-id="'+a.i+'" style="'+(a.read?'opacity:.6':'')+'">'+sevBadge(a.sev)+'<div class="tx"><b style="font-weight:500">'+esc(a.t)+'</b><span>'+when(a.ago)+(a.read?' · 확인함':'')+'</span></div></button>'}).join('')+'</div>'}));
 return cards+'<div class="split"><div class="stack">'+trend+chart+'</div>'+svc+'</div><div class="split">'+errs+'<div class="stack">'+dep+alerts+'</div></div>'}

function InfraCard(s){
 var k=f(),metrics='',st=s.st;
 if(s.id==='cf')metrics=M('요청 수',fmt(s.req*k))+M('오류 수',fmt(s.err*k))+M('응답 시간',ms(s.avg));
 if(s.id==='run')metrics=M('서비스 상태',badge(st,st==='warn'?'주의':'정상'))+M('인스턴스','2 <span class="note">/ 최대 10</span>')+M('요청 수',fmt(s.req*k))+M('CPU 사용률',meter(38,'ok'))+M('메모리 사용률',meter(71,'warn'))+M('최근 콜드 스타트','52초 <span class="note">(샘플)</span>');
 if(s.id==='api')metrics=M('서버 상태',badge('ok','정상'))+M('요청 처리 시간',ms(s.avg))+M('서버 오류(5xx)',fmt(s.err*k)+'건');
 if(s.id==='sb')metrics=M('DB 연결',badge('ok','연결됨'))+M('쿼리 오류',fmt(s.err*k)+'건')+M('DB 응답 시간',ms(s.avg));
 return '<button class="card-click" data-act="svcModal" data-id="'+s.id+'"><div class="top"><b>'+s.name+'</b>'+badge(st)+'</div><div class="mgrid">'+metrics+'</div><div class="toolbar"><div>'+sparkline(s.spark,st)+'<div class="note">응답 시간 추이</div></div><span class="more">상세 보기 →</span></div></button>'}
function meter(p,st){return '<span style="display:flex;align-items:center;gap:8px">'+p+'%<span style="flex:1;min-width:48px;height:6px;border-radius:3px;background:var(--surface2);overflow:hidden"><span style="display:block;height:100%;width:'+p+'%;background:var(--'+st+')"></span></span></span>'}
function M(l,v){return '<div class="m"><span>'+l+'</span><b class="num">'+v+'</b></div>'}
function pageInfra(){
 var bar='<div class="panel"><div class="pbody toolbar"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>전체 인프라 상태</b>'+badge('warn')+'<span class="note">Cloud Run 첫 요청 지연이 감지되었습니다.</span></div>'+DateRangePicker()+'</div></div>';
 var cards=guard('card',function(){return '<div class="grid2">'+['cf','run','api','sb'].map(function(id){return InfraCard(SERVICES.filter(function(x){return x.id===id})[0])}).join('')+'</div>'});
 var wrap=(S.view==='ok')?cards:'<div class="panel">'+cards+'</div>';
 return bar+wrap+'<p class="note">Cloud Run CPU·메모리 사용률은 샘플 값입니다. 실제 연동 때는 수집 가능한 지표만 표시하고, 수집하지 않는 지표는 “미수집”으로 보여 줍니다.</p>'}

function pageApi(){
 var names=['전체','Cloudflare Workers','FastAPI','Supabase','Claude API'];
 var rows=APIS.map(function(a,i){return {i:i,svc:a[0],ep:a[1],st:a[2],ms:a[3],req:a[4],er:a[5],chk:a[6]}}).filter(function(r){return S.svcFilter==='전체'||r.svc===S.svcFilter});
 var all=APIS.length,ok=APIS.filter(function(a){return a[2]==='ok'}).length,er=APIS.filter(function(a){return a[2]==='err'}).length;
 var avg=Math.round(sum(APIS.map(function(a){return a[3]}))/all);
 var cards='<div class="grid4">'+SummaryCard({label:'전체 API 수',value:all,unit:'개',sub:'<span>4개 서비스 대상</span>'})+
  SummaryCard({label:'정상 API 수',value:ok,unit:'개',badge:badge('ok'),sub:'<span>주의 '+APIS.filter(function(a){return a[2]==='warn'}).length+'개</span>'})+
  SummaryCard({label:'오류 API 수',value:er,unit:'개',badge:badge('err'),sub:'<span>/api/files/upload 오류율 높음</span>'})+
  SummaryCard({label:'평균 응답 시간',value:fmt(avg),unit:'ms',sub:'<span>이전 기간 대비 '+deltaHtml(3.1,true)+'</span>'})+'</div>';
 var cols=[{h:'서비스명',k:function(r){return r.svc},f:function(r){return esc(r.svc)}},{h:'Endpoint',k:function(r){return r.ep},f:function(r){return '<span class="mono">'+esc(r.ep)+'</span>'}},{h:'상태',k:function(r){return {ok:0,warn:1,err:2}[r.st]},f:function(r){return badge(r.st)}},{h:'응답 시간',r:1,k:function(r){return r.ms},f:function(r){return ms(r.ms)}},{h:'요청 수',r:1,k:function(r){return r.req},f:function(r){return fmt(r.req)}},{h:'오류율',r:1,k:function(r){return r.er},f:function(r){return r.er+'%'}},{h:'최근 확인',k:function(r){return r.chk},f:function(r){return r.chk+'분 전'}}];
 var tbl=panelFixed('API별 상태','행을 클릭하면 시간별 응답 시간과 오류 추이를 볼 수 있습니다',guard('table',function(){return '<div class="pbody flush">'+DataTable(cols,sortRows('api',cols,rows),'apiModal','api')+'</div>'}),'<div class="toolbar">'+Seg('svcFilter',names.map(function(n){return [n,n]}),S.svcFilter)+'</div>');
 return cards+tbl}

function filteredLogs(){var l=S.lf,q=l.q.trim().toLowerCase(),lim=S.range==='custom'?null:RANGE_L[S.range]&&({'1h':60,'24h':1440,'7d':10080,'30d':43200})[S.range];
 return LOGS.filter(function(x){
  if(lim&&x.ago>lim)return false;
  if(S.range==='custom'){var d=new Date(NOW.getTime()-x.ago*60000),ds=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());if(S.from&&ds<S.from)return false;if(S.to&&ds>S.to)return false}
  if(l.type&&x.type!==l.type)return false;if(l.sev&&x.sev!==l.sev)return false;if(l.path&&x.path!==l.path)return false;
  if(l.code&&String(x.code)!==String(l.code))return false;if(l.proc&&x.proc!==l.proc)return false;
  if(q&&(x.msg+' '+x.trace).toLowerCase().indexOf(q)<0)return false;return true})}
function pageLogs(){
 var rows=filteredLogs(),size=8,pg=Math.min(S.lp,Math.max(1,Math.ceil(rows.length/size)));
 var c={all:rows.length,err:rows.filter(function(x){return x.sev==='ERROR'||x.sev==='CRITICAL'}).length,warn:rows.filter(function(x){return x.sev==='WARNING'}).length,open:rows.filter(function(x){return x.proc==='미처리'}).length};
 var cards='<div class="grid4">'+SummaryCard({label:'전체 로그 수',value:fmt(c.all),unit:'건',sub:'<span>'+RANGE_L[S.range]+' 기준 (샘플 목록)</span>'})+
  SummaryCard({label:'오류 로그 수',value:c.err,unit:'건',badge:badge('err'),sub:'<span>ERROR · CRITICAL</span>'})+
  SummaryCard({label:'경고 로그 수',value:c.warn,unit:'건',badge:badge('warn'),sub:'<span>WARNING</span>'})+
  SummaryCard({label:'미처리 오류 수',value:c.open,unit:'건',sub:'<span>처리 상태가 미처리인 로그</span>'})+'</div>';
 var cols=[{h:'발생 시간',k:function(l){return -l.ago},f:function(l){return '<span class="mono">'+when(l.ago)+'</span>'}},{h:'심각도',k:function(l){return {INFO:0,WARNING:1,ERROR:2,CRITICAL:3}[l.sev]},f:function(l){return sevBadge(l.sev)}},{h:'서비스',k:function(l){return l.svc},f:function(l){return l.svc}},{h:'오류 유형',k:function(l){return l.type},f:function(l){return esc(l.type)}},{h:'API 경로',k:function(l){return l.path},f:function(l){return '<span class="mono">'+esc(l.path)+'</span>'}},{h:'상태 코드',r:1,k:function(l){return l.code},f:function(l){return l.code}},{h:'처리 상태',k:function(l){return l.proc},f:function(l){return procBadge(l.proc)}},{h:'상세',f:function(l){return '<button class="lnk" data-act="logModal" data-id="'+l.i+'">상세 보기</button>'}}];
 var tb=panelFixed('로그 목록','클릭하면 상세 내용을 확인합니다',guard('table',function(){return '<div class="pbody flush">'+DataTable(cols,sortRows('logs',cols,rows).slice((pg-1)*size,pg*size),'logModal','logs')+'</div>'+(rows.length?Pagination(rows.length,pg,size,'lp'):'')}));
 return cards+panelFixed('검색 및 필터','',SearchFilter(),'<div class="toolbar"><span class="note">기간</span>'+DateRangePicker()+'</div>')+tb}

function pageDeploy(){
 var ok=DEPLOYS.filter(function(d){return d.res==='성공'}).length,bad=DEPLOYS.length-ok,size=6,pg=Math.min(S.dp,Math.ceil(DEPLOYS.length/size));
 var cards='<div class="grid4">'+SummaryCard({label:'최근 배포',value:DEPLOYS[0].ver,sub:'<span>'+when(DEPLOYS[0].ago)+'</span>'+resBadge(DEPLOYS[0].res)})+
  SummaryCard({label:'배포 성공',value:ok,unit:'건',badge:badge('ok'),sub:'<span>최근 '+DEPLOYS.length+'건 기준</span>'})+
  SummaryCard({label:'배포 실패',value:bad,unit:'건',badge:badge('err'),sub:'<span>실패 시 직전 revision 유지</span>'})+
  SummaryCard({label:'성공률',value:Math.round(ok/DEPLOYS.length*100),unit:'%',sub:'<span>수동 배포 '+DEPLOYS.filter(function(d){return d.by==='수동 배포'}).length+'건 포함</span>'})+'</div>';
 var cols=[{h:'배포 버전',k:function(d){return -d.i},f:function(d){return '<span class="mono">'+d.ver+'</span>'}},{h:'배포 일시',k:function(d){return -d.ago},f:function(d){return '<span class="mono">'+when(d.ago)+'</span>'}},{h:'배포 환경',k:function(d){return d.env},f:function(d){return d.env==='prod'?badge('info','prod'):badge('mute','dev').replace(/<svg.*?<\/svg>/,'')}},{h:'배포 담당자',k:function(d){return d.by},f:function(d){return d.by}},{h:'배포 결과',k:function(d){return d.res},f:function(d){return resBadge(d.res)}},{h:'상세 내역',f:function(d){return '<button class="lnk" data-act="depModal" data-id="'+d.i+'">보기</button>'}}];
 var dep=panelFixed('배포 관리','최근 배포 이력',guard('table',function(){return '<div class="pbody flush">'+DataTable(cols,sortRows('dep',cols,DEPLOYS).slice((pg-1)*size,pg*size),'depModal','dep')+Pagination(DEPLOYS.length,pg,size,'dp')+'</div>'}));
 var db=panelFixed('DB 관리','Supabase / PostgreSQL · 조회 전용',guard('card',function(){return '<div class="pbody"><div class="mgrid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">'+M('DB 연결 상태',badge('ok','연결됨'))+M('DB 응답 시간','18ms')+M('쿼리 오류 (24시간)','3건')+M('최근 백업 시간','<span class="mono" style="font-size:15px">'+when(380)+'</span>')+M('백업 상태',badge('ok','성공'))+'</div><p class="note" style="margin:14px 0 0">백업 시간과 상태는 샘플입니다. 실제 연동은 Supabase 요금제와 API 접근 범위를 확인한 뒤 진행합니다. 이 영역에는 데이터 수정·삭제 기능이 없습니다.</p></div>'}));
 return cards+dep+db}

/* ---------- modals ---------- */
function modalShell(title,sub,body){return '<div class="modal-bg" data-act="closeModal"><div class="modal" role="dialog" aria-modal="true" aria-label="'+esc(title)+'"><header><div><h3>'+esc(title)+'</h3>'+(sub?'<small>'+sub+'</small>':'')+'</div><button class="btn" data-act="closeModal" id="mClose">닫기</button></header><div class="mb">'+body+'</div></div></div>'}
function DetailModal(){var m=S.modal;if(!m)return '';
 if(m.t==='log'){var l=LOGS[m.id],rel=LOGS.filter(function(x){return x.i!==l.i&&(x.svc===l.svc||x.path===l.path)}).slice(0,3);
  return modalShell('로그 상세',sevBadge(l.sev)+' '+procBadge(l.proc),
   '<dl class="kv"><dt>오류 메시지</dt><dd>'+esc(l.msg)+'</dd><dt>발생 시간</dt><dd class="mono">'+when(l.ago)+'</dd><dt>관련 서비스</dt><dd>'+l.svc+'</dd><dt>API 경로</dt><dd class="mono">'+esc(l.path)+'</dd><dt>상태 코드</dt><dd>'+l.code+'</dd><dt>Trace ID</dt><dd class="mono">'+l.trace+' <button class="lnk" data-act="copy" data-v="'+l.trace+'">복사</button></dd><dt>처리 상태</dt><dd><select id="m-proc" data-lproc="'+l.i+'" aria-label="처리 상태" style="height:32px;border:1px solid var(--line);background:var(--surface);border-radius:6px;padding:0 8px">'+['미처리','확인 중','해결'].map(function(p){return '<option'+(p===l.proc?' selected':'')+'>'+p+'</option>'}).join('')+'</select></dd><dt>조치 내용</dt><dd><textarea id="m-note" rows="3" placeholder="조치 내용을 입력하세요" style="width:100%;border:1px solid var(--line);background:var(--surface);color:var(--fg);border-radius:6px;padding:8px;font:inherit">'+esc(l.note!==undefined?l.note:(ACT[l.proc]||''))+'</textarea><div style="margin-top:6px"><button class="btn primary" data-act="saveNote" data-id="'+l.i+'">조치 내용 저장</button></div></dd></dl>'+
   '<div><p class="sec-t">관련 로그</p><div class="rel">'+(rel.length?rel.map(function(x){return '<div><span class="mono">'+when(x.ago)+'</span><span>'+esc(x.msg)+'</span></div>'}).join(''):'<div>관련 로그가 없습니다.</div>')+'</div></div>')}
 if(m.t==='dep'){var d=DEPLOYS[m.id];
  return modalShell('배포 상세 · '+d.ver,resBadge(d.res),'<dl class="kv"><dt>배포 일시</dt><dd class="mono">'+when(d.ago)+'</dd><dt>배포 환경</dt><dd>'+d.env+'</dd><dt>배포 담당자</dt><dd>'+d.by+'</dd><dt>소요 시간</dt><dd>'+d.dur+'</dd><dt>커밋</dt><dd class="mono">'+d.sha+'</dd><dt>변경 내용</dt><dd>'+d.note+'</dd></dl>')}
 if(m.t==='api'){var a=APIS[m.id],r=rnd(m.id*13+5);
  var lat=wave(a[3],a[3]*.5,m.id*17+3),er=wave(Math.max(.1,a[5]),a[5]*.8+.2,m.id*19+1).map(function(v){return +(v).toFixed(2)});
  return modalShell(a[0]+' · '+a[1],badge(a[2]),'<div><p class="sec-t">시간별 응답 시간 (ms, 샘플)</p>'+MonitoringChart({type:'line',labels:HOURS,series:[{values:lat,c:'accent'}],area:1,h:170,aria:'시간별 응답 시간'})+'</div><div><p class="sec-t">시간별 오류율 (%, 샘플)</p>'+MonitoringChart({type:'line',labels:HOURS,series:[{values:er,c:'err'}],area:1,h:150,fy:function(v){return v.toFixed(1)},aria:'시간별 오류율'})+'</div>')}
 if(m.t==='svc'){var s=SERVICES.filter(function(x){return x.id===m.id})[0];
  return modalShell(s.name,badge(s.st)+' '+esc(s.desc),'<div class="mgrid">'+M('요청 수 ('+RANGE_L[S.range]+')',fmt(s.req*f()))+M('오류 수',fmt(s.err*f()))+M('평균 응답 시간',ms(s.avg))+'</div><div><p class="sec-t">응답 시간 추이 (ms, 샘플)</p>'+MonitoringChart({type:'line',labels:HOURS,series:[{values:s.spark.concat(s.spark).slice(0,24),c:s.st==='warn'?'warn':'accent'}],area:1,h:190,aria:'응답 시간 추이'})+'</div>'+(s.id==='run'?'<div class="mgrid">'+M('CPU 사용률',meter(38,'ok'))+M('메모리 사용률',meter(71,'warn'))+M('인스턴스','2 / 최대 10')+'</div>':''))}
 return ''}

/* ---------- live (서버 연결 모드: /admin/ops/summary, /admin/ops/apis) ---------- */
/* 서버에서 받은 문자열은 모두 esc() 를 거쳐 HTML 에 넣는다. 서버에 없는 값(인프라·배포·오류 내역)은 샘플을 섞지 않고 "미연결" 로 보여 준다. */
var LIVE_RANGES=[['1h','1시간'],['24h','24시간'],['7d','7일']];
var LS={sum:null,apis:null,infra:null,errs:null,err:null,loading:false},seq=0;
function liveRange(){return S.range==='1h'||S.range==='7d'?S.range:'24h'}
function liveErr(e){
 if(e&&e.status===403)return {t:'운영자 권한이 없습니다',d:'이 계정은 운영 관리자 허용 목록에 없습니다.'};
 if(e&&e.code==='network_error')return {t:'서버에 연결하지 못했습니다',d:'네트워크와 서버 주소를 확인하세요.'};
 return {t:'데이터를 불러오지 못했습니다',d:'잠시 후 다시 시도하세요.'}}
function soft(path){return request(path).catch(function(e){return {failed:e}})}  // 인프라·오류 조회가 실패해도 요청 지표 화면은 막지 않는다
function fetchLive(rk){return Promise.all([request('/admin/ops/summary?range='+rk),request('/admin/ops/apis?range='+rk),soft('/admin/ops/infra'),soft('/admin/ops/errors?range='+rk+'&limit=100')])}
function loadLive(){
 var rk=liveRange(),my=++seq;
 if(LS.sum&&LS.sum.range!==rk){LS.sum=LS.apis=LS.infra=LS.errs=null}  // 다른 기간의 숫자를 남겨 두지 않는다
 LS.loading=true;LS.err=null;render();
 return fetchLive(rk).then(function(r){
  if(my!==seq)return;LS.sum=r[0];LS.apis=r[1];LS.infra=r[2];LS.errs=r[3];
 }).catch(function(e){if(my!==seq)return;LS.err=liveErr(e);LS.sum=LS.apis=LS.infra=LS.errs=null;
 }).then(function(){if(my!==seq)return;LS.loading=false;S.updated=new Date();render()})}
function liveLabel(iso,rk){var d=new Date(iso);return rk==='7d'?pad(d.getMonth()+1)+'-'+pad(d.getDate()):pad(d.getHours())+':'+pad(d.getMinutes())}
function pct(r){return (r*100).toFixed(2)+'%'}
function LiveBar(){
 var warn=LS.sum&&!LS.sum.metrics_enabled?'<span class="note" style="color:var(--warn)">서버의 요청 계측이 꺼져 있어 수치가 0 일 수 있습니다.</span>':'';
 return '<div class="sample live"><span><strong>실서버 데이터</strong> 요청 지표(경로 패턴·상태코드·응답 시간 집계), 오류 이벤트, Cloud Run 상태를 표시합니다. 평균·최대 응답 시간만 제공하며 p95 는 없습니다. 시각은 이 브라우저의 시간대 기준입니다. '+warn+'</span>'+
  (LS.loading?'<span class="note">갱신 중…</span>':'')+'<span class="toolbar" style="gap:8px"><span>기간</span>'+Seg('range',LIVE_RANGES,liveRange())+'</span></div>'}
function liveNotConnected(what){return '<div class="panel"><div class="state">'+IC.empty+'<b>아직 서버와 연결되지 않았습니다</b><span>'+esc(what)+' 은(는) 저장 테이블과 조회 API 가 만들어진 뒤 표시됩니다. 샘플 값은 섞어 보이지 않습니다.</span></div></div>'}
function liveState(){
 if(LS.loading&&!LS.sum)return '<div class="panel"><div style="padding:16px;display:flex;flex-direction:column;gap:10px"><div class="sk" style="height:60px"></div><div class="sk" style="height:170px"></div></div></div>';
 if(LS.err)return '<div class="panel"><div class="state err">'+IC.fail+'<b>'+esc(LS.err.t)+'</b><span>'+esc(LS.err.d)+'</span><button class="btn" data-act="refresh">다시 시도</button></div></div>';
 return ''}
function liveDashboard(){
 var st=liveState();if(st)return st;if(!LS.sum)return '';
 var s=LS.sum,rk=s.range;
 var cards='<div class="grid4">'+
  SummaryCard({label:'API 요청 수 ('+RANGE_L[rk]+')',value:fmt(s.requests),unit:'건',sub:'<span>4xx '+fmt(s.errors_4xx)+'건 포함</span>'})+
  SummaryCard({label:'서버 오류 (5xx)',value:fmt(s.errors_5xx),unit:'건',badge:s.errors_5xx?badge('err'):badge('ok'),sub:'<span>오류율 <b>'+pct(s.error_rate)+'</b></span>'})+
  SummaryCard({label:'평균 응답 시간',value:fmt(s.avg_ms),unit:'ms',sub:'<span>최대 '+fmt(s.max_ms)+'ms</span>'})+
  SummaryCard({label:'수집 구간 수',value:fmt(s.series.filter(function(p){return p.requests>0}).length),unit:'개',sub:'<span>요청이 있었던 구간</span>'})+'</div>';
 var labels=s.series.map(function(p){return liveLabel(p.t,rk)});
 var chart=panelFixed('요청 추이','정상 요청과 5xx 실패 요청 · 막대에 마우스를 올리면 값을 볼 수 있습니다',
  '<div class="pbody">'+(s.requests?'<div class="toolbar" style="margin-bottom:8px"><div class="legend"><span><i style="background:var(--bar)"></i>정상</span><span><i style="background:var(--err)"></i>5xx 실패</span></div><div class="readout" id="readout-ch">막대에 마우스를 올리면 구간별 값을 볼 수 있습니다.</div></div>'+MonitoringChart({type:'bar',labels:labels,a:s.series.map(function(p){return p.requests-p.errors}),b:s.series.map(function(p){return p.errors}),id:'ch',aria:'구간별 정상 요청과 실패 요청 막대 차트'}):'<div class="state">'+IC.empty+'<b>이 기간에 집계된 요청이 없습니다</b><span>계측이 켜져 있는지, 기간을 넓혀야 하는지 확인하세요.</span></div>')+'</div>');
 return cards+chart+liveNotConnected('배포 이력과 DB 관리')}
function liveApis(){
 var st=liveState();if(st)return st;if(!LS.apis)return '';
 var items=LS.apis.items.map(function(a,i){return {i:i,m:a.method,r:a.route,n:a.requests,c4:a.c4xx,c5:a.c5xx,er:a.error_rate,avg:a.avg_ms,max:a.max_ms}});
 var tot=sum(items.map(function(x){return x.n})),bad=items.filter(function(x){return x.c5>0}).length;
 var avg=tot?Math.round(sum(items.map(function(x){return x.avg*x.n}))/tot):0;
 var trunc=!!LS.apis.truncated;
 var cards='<div class="grid4">'+SummaryCard({label:'호출된 API 경로',value:fmt(LS.apis.total_routes),unit:'개',sub:'<span>'+(trunc?'요청 수 상위 '+fmt(items.length)+'개만 표시':'경로 패턴 기준')+'</span>'})+
  SummaryCard({label:'5xx 가 있는 경로',value:fmt(bad),unit:'개',badge:bad?badge('err'):badge('ok'),sub:trunc?'<span>표시된 경로 기준</span>':''})+
  SummaryCard({label:'총 요청 수',value:fmt(tot),unit:'건',sub:trunc?'<span>표시된 경로만 합산</span>':''})+
  SummaryCard({label:'평균 응답 시간',value:fmt(avg),unit:'ms',sub:'<span>'+(trunc?'표시된 경로의 ':'')+'요청 수 가중 평균</span>'})+'</div>';
 var cols=[{h:'메서드',k:function(r){return r.m},f:function(r){return '<span class="mono">'+esc(r.m)+'</span>'}},
  {h:'경로 패턴',k:function(r){return r.r},f:function(r){return '<span class="mono">'+esc(r.r)+'</span>'}},
  {h:'요청 수',r:1,k:function(r){return r.n},f:function(r){return fmt(r.n)}},
  {h:'4xx',r:1,k:function(r){return r.c4},f:function(r){return fmt(r.c4)}},
  {h:'5xx',r:1,k:function(r){return r.c5},f:function(r){return fmt(r.c5)}},
  {h:'5xx 비율',r:1,k:function(r){return r.er},f:function(r){return pct(r.er)}},
  {h:'평균 응답',r:1,k:function(r){return r.avg},f:function(r){return ms(r.avg)}},
  {h:'최대 응답',r:1,k:function(r){return r.max},f:function(r){return ms(r.max)}}];
 return cards+panelFixed('API 경로별 요청 현황','실제 주소가 아니라 경로 패턴(예: /groups/{group_id})으로 집계됩니다',
  '<div class="pbody flush">'+DataTable(cols,sortRows('lapi',cols,items),'','lapi')+'</div>')}
function softFail(what,x){
 var e=x.failed,d=e&&e.status===404?'서버에 이 조회 기능이 아직 배포되지 않았습니다.':(e&&e.status===403?'운영자 권한이 없습니다.':'잠시 후 다시 시도하세요.');
 return '<div class="panel"><div class="state err">'+IC.fail+'<b>'+esc(what)+'을(를) 불러오지 못했습니다</b><span>'+esc(d)+'</span><button class="btn" data-act="refresh">다시 시도</button></div></div>'}
function pctOrNone(v){return v==null?'미수집':(v*100).toFixed(1)+'%'}
function numOrNone(v,unit){return v==null?'미수집':fmt(v)+(unit||'')}
function liveInfra(){
 var st=liveState();if(st)return st;if(!LS.infra)return '';
 if(LS.infra.failed)return softFail('인프라 상태',LS.infra);
 var x=LS.infra;
 if(!x.collected)return '<div class="panel"><div class="state">'+IC.empty+'<b>인프라 상태를 수집하지 않고 있습니다</b><span>'+esc(x.reason||'')+' 샘플 값은 섞어 보이지 않습니다.</span></div></div>';
 var s=x.service||{},m=x.metrics||{};
 var cpuMode=s.cpu_allocation==='request'?'요청 처리 중에만 할당':s.cpu_allocation==='instance'?'항상 할당':'미수집';
 var note=x.reason?'<p class="note" style="color:var(--warn)">일부만 수집했습니다: '+esc(x.reason)+'</p>':'';
 var card='<div class="grid2"><div class="panel"><header><div><h2>Cloud Run 서비스</h2><small>'+esc(s.name||'')+' · '+esc(s.region||'')+'</small></div></header><div class="pbody"><div class="mgrid">'+
  M('현재 리비전',esc(s.revision||'미수집'))+M('최소 인스턴스',numOrNone(s.min_instances))+M('최대 인스턴스',numOrNone(s.max_instances))+M('CPU 할당',esc(cpuMode))+'</div></div></div>'+
  '<div class="panel"><header><div><h2>최근 '+fmt(x.window_minutes||0)+'분 사용량</h2><small>Cloud Monitoring</small></div></header><div class="pbody"><div class="mgrid">'+
  M('활성 인스턴스',numOrNone(m.instances_active))+M('유휴 인스턴스',numOrNone(m.instances_idle))+M('CPU 사용률(p99)',pctOrNone(m.cpu_p99))+M('메모리 사용률(p99)',pctOrNone(m.memory_p99))+'</div></div></div></div>';
 return card+note+'<p class="note">서버가 약 60초 동안 캐시한 값입니다('+esc(new Date(x.fetched_at).toLocaleTimeString())+' 조회). Cloud Run 요청 기반 CPU 에서는 요청 밖 CPU 해석이 달라질 수 있습니다.</p>'}
function liveErrors(){
 var st=liveState();if(st)return st;if(!LS.errs)return '';
 if(LS.errs.failed)return softFail('오류 내역',LS.errs);
 var d=LS.errs;
 if(!d.errors_enabled&&!d.items.length)return '<div class="panel"><div class="state">'+IC.empty+'<b>서버의 오류 수집이 꺼져 있습니다</b><span>OPS_ERRORS_ENABLED 를 켜면 5xx·처리되지 않은 예외·401/403 이 여기에 쌓입니다.</span></div></div>';
 var kinds={server_error:'서버 오류',auth_failure:'인증 실패'};
 var items=d.items.map(function(e){return {i:e.id,k:kinds[e.kind]||e.kind,sev:e.severity,t:e.event_type,m:e.method,r:e.route,s:e.status,n:e.occurrences,f:e.first_seen,l:e.last_seen,msg:e.message,loc:e.location}});
 var cols=[{h:'종류',k:function(r){return r.k},f:function(r){return badge(r.sev==='error'?'err':'warn',r.k)}},
  {h:'유형',k:function(r){return r.t},f:function(r){return '<span class="mono">'+esc(r.t)+'</span>'}},
  {h:'경로',k:function(r){return r.r},f:function(r){return '<span class="mono">'+esc(r.m)+' '+esc(r.r)+'</span>'}},
  {h:'상태',r:1,k:function(r){return r.s},f:function(r){return r.s}},
  {h:'횟수',r:1,k:function(r){return r.n},f:function(r){return fmt(r.n)}},
  {h:'마지막 발생',k:function(r){return r.l},f:function(r){return esc(new Date(r.l).toLocaleString())}},
  {h:'위치',f:function(r){return '<span class="mono">'+esc(r.loc||'-')+'</span>'}},
  {h:'메시지(가림)',f:function(r){return esc(r.msg||'-')}}];
 var cards='<div class="grid4">'+SummaryCard({label:'오류 종류 수 ('+RANGE_L[d.range]+')',value:fmt(d.total),unit:'개',badge:d.total?badge('warn'):badge('ok'),sub:d.truncated?'<span>상위 '+fmt(items.length)+'개만 표시</span>':''})+
  SummaryCard({label:'발생 횟수 합계',value:fmt(sum(items.map(function(x){return x.n}))),unit:'건',sub:d.truncated?'<span>표시된 항목만 합산</span>':''})+'</div>';
 return cards+panelFixed('오류 내역','같은 오류는 한 줄로 합쳐 횟수를 셉니다 · 메시지는 개인정보를 가린 값입니다',
  '<div class="pbody flush">'+DataTable(cols,sortRows('lerr',cols,items),'','lerr')+'</div>')}
function livePage(){
 var body={dashboard:liveDashboard,api:liveApis,infra:liveInfra,
  logs:liveErrors,deploy:function(){return liveNotConnected('배포 이력과 DB 관리')}}[S.page]();
 return (S.page==='dashboard'||S.page==='api'||S.page==='infra'||S.page==='logs'?LiveBar():'')+body}

/* ---------- login ---------- */
var LOGIN_HTML='<div class="login-card"><div class="login-head"><b>GABI</b><span>OPERATIONS ADMIN</span></div>'+
 '<form class="login-body" data-login="1" autocomplete="off"><h1>운영 관리자 로그인</h1>'+
 '<div class="field"><label for="l-id">아이디</label><input id="l-id" type="text" autocomplete="off" spellcheck="false" required></div>'+
 '<div class="field"><label for="l-pw">비밀번호</label><input id="l-pw" type="password" autocomplete="off" required></div>'+
 '<div class="login-err" id="l-err" role="alert"></div>'+
 '<button class="btn primary" type="submit">로그인</button>'+
 '<div class="login-note">'+(LIVE?'운영 서버 계정으로 로그인합니다. 운영자 허용 목록에 있는 계정만 화면을 볼 수 있습니다.':'샘플 화면입니다. 서버에 연결되기 전이라 실제 인증이 아니며, 화면의 모든 값은 가짜입니다.')+'</div></form></div>';
var fails=0,lockUntil=0,busy=false,authed=false;
function showLogin(){$('#app').hidden=true;$('#modalRoot').innerHTML='';var r=$('#loginRoot');r.hidden=false;if(!r.innerHTML)r.innerHTML=LOGIN_HTML}
function enterApp(){fails=0;S.auth=true;var r=$('#loginRoot');r.innerHTML='';r.hidden=true;$('#app').hidden=false;render()}
function failLogin(msg){var err=$('#l-err');fails++;$('#l-pw').value='';
 if(fails>=5){lockUntil=Date.now()+30000;fails=0;err.textContent='시도가 너무 많습니다. 30초 뒤에 다시 시도하세요'}else err.textContent=msg}
function tryLogin(){
 var err=$('#l-err'),acc=window.GABI_SAMPLE_ACCOUNT,now=Date.now();
 if(now<lockUntil){err.textContent='시도가 너무 많습니다. '+Math.ceil((lockUntil-now)/1000)+'초 뒤에 다시 시도하세요';return}
 if(LIVE){
  if(busy)return;busy=true;authed=false;err.textContent='';
  var id=$('#l-id').value,pw=$('#l-pw').value;
  // 로그인 → 운영 API 첫 조회가 운영자 확인을 겸한다. 403 이면 토큰을 버리고 로그인 화면에 머문다.
  apiLogin(id,pw).then(function(){authed=true;var rk=liveRange(),my=++seq;return fetchLive(rk).then(function(r){
   if(my!==seq)return;LS.sum=r[0];LS.apis=r[1];LS.err=null;LS.loading=false;enterApp()})}).catch(function(e){
   setToken(null);
   if(e&&e.status===403){err.textContent='운영 관리자 권한이 없는 계정입니다';$('#l-pw').value=''}
   else if(e&&e.status===429)err.textContent='시도가 너무 많습니다. 잠시 후 다시 시도하세요';
   else if(e&&e.code==='network_error')err.textContent='서버에 연결하지 못했습니다';
   else if(e&&e.status===401&&authed)err.textContent='로그인은 됐지만 서버가 권한 확인을 거절했습니다. 잠시 후 다시 시도하세요';
   else if(e&&(e.status===401||e.status===400||e.status===422))failLogin('아이디 또는 비밀번호가 올바르지 않습니다');
   else err.textContent='로그인하지 못했습니다. 잠시 후 다시 시도하세요';
  }).then(function(){busy=false});
  return}
 if(!acc||!acc.id){err.textContent='샘플 계정이 설정되지 않았습니다 (js/sample-account.js)';return}
 if($('#l-id').value===acc.id&&$('#l-pw').value===acc.pw){enterApp();return}
 failLogin('아이디 또는 비밀번호가 올바르지 않습니다')}
function doLogout(){if(LIVE){seq++;apiLogout();LS.sum=LS.apis=LS.infra=LS.errs=LS.err=null;LS.loading=false}S.auth=false;S.modal=null;S.notif=false;$('#app').classList.remove('open');render()}
if(LIVE)setUnauthorizedHandler(function(){if(busy)return;doLogout();var e=$('#l-err');if(e)e.textContent='로그인이 만료되었습니다. 다시 로그인하세요'});

/* ---------- render ---------- */
function render(){
 if(!S.auth){showLogin();return}
 Sidebar();Header();
 if(LIVE){$('#content').innerHTML=livePage();$('#modalRoot').innerHTML='';return}
 var body={dashboard:pageDashboard,infra:pageInfra,api:pageApi,logs:pageLogs,deploy:pageDeploy}[S.page]();
 $('#content').innerHTML=SampleBar()+body;
 $('#modalRoot').innerHTML=DetailModal();
 if(S.modal){var c=$('#mClose');if(c)c.focus()}
}
function toast(t){var el=document.createElement('div');el.className='toast';el.textContent=t;$('#toastRoot').appendChild(el);setTimeout(function(){el.remove()},2200)}
function go(id){S.page=id;S.lp=1;S.dp=1;S.modal=null;S.notif=false;$('#app').classList.remove('open');if(location.hash!=='#'+id)history.replaceState(null,'','#'+id);render();window.scrollTo(0,0)}

document.addEventListener('click',function(e){
 var t=e.target.closest('[data-act]');
 if(!t){if(S.notif&&!e.target.closest('.pop')){S.notif=false;Header()}return}
 var a=t.dataset.act;
 if(a==='closeModal'){if(e.target.closest('.modal')&&!e.target.closest('#mClose'))return;S.modal=null;render();return}
 if(a==='nav')return go(t.dataset.id);
 if(a==='openMenu'){$('#app').classList.add('open');return}
 if(a==='closeMenu'){$('#app').classList.remove('open');return}
 if(a==='logout'){doLogout();return}
 if(a==='notif'){S.notif=!S.notif;Header();return}
 if(a==='refresh'&&LIVE){loadLive();return}
 if(a==='refresh'){var keep=S.view;S.view='loading';render();setTimeout(function(){S.view=keep==='loading'?'ok':keep;S.updated=new Date();render()},700);return}
 if(a==='retry'){S.view='ok';S.updated=new Date();render();return}
 if(a==='seg'){var k=t.dataset.k,v=t.dataset.v;S[k]=v;if(LIVE&&k==='range'){loadLive();return}if(k==='svcFilter'||k==='range')S.lp=1;render();return}
 if(a==='sort'){var cur=S.sort[t.dataset.t],c=+t.dataset.c;S.sort[t.dataset.t]=cur&&cur.c===c?{c:c,d:-cur.d}:{c:c,d:1};S.lp=1;S.dp=1;render();return}
 if(a==='page'){var n=+t.dataset.v;if(n<1)return;S[t.dataset.k]=n;render();return}
 if(a==='resetF'){S.lf={type:'',sev:'',path:'',code:'',proc:'',q:''};S.lp=1;render();return}
 if(a==='saveNote'){var ta=$('#m-note');LOGS[+t.dataset.id].note=ta?ta.value:'';toast('조치 내용을 저장했습니다');return}
 if(a==='readAlert'){ALERTS[+t.dataset.id].read=true;render();return}
 if(a==='logModal'){S.modal={t:'log',id:+t.dataset.id};render();return}
 if(a==='depModal'){S.modal={t:'dep',id:+t.dataset.id};render();return}
 if(a==='apiModal'){S.modal={t:'api',id:+t.dataset.id};render();return}
 if(a==='svcModal'){S.modal={t:'svc',id:t.dataset.id};render();return}
 if(a==='copy'){var v2=t.dataset.v;var ok=function(){toast('Trace ID를 복사했습니다')};
  try{navigator.clipboard.writeText(v2).then(ok,function(){toast('복사하지 못했습니다. 직접 선택해 복사하세요')})}catch(x){toast('복사하지 못했습니다. 직접 선택해 복사하세요')}return}
});
document.addEventListener('submit',function(e){if(e.target&&e.target.dataset&&e.target.dataset.login){e.preventDefault();tryLogin()}});
document.addEventListener('keydown',function(e){
 if(e.key==='Escape'&&S.modal){S.modal=null;render()}
 if((e.key==='Enter'||e.key===' ')&&e.target.matches&&e.target.matches('tr.click')){e.preventDefault();e.target.click()}
});
document.addEventListener('change',function(e){
 var el=e.target;
 if(el.dataset&&el.dataset.lproc){LOGS[+el.dataset.lproc].proc=el.value;toast('처리 상태를 '+el.value+'(으)로 변경했습니다');render();return}
 if(el.dataset&&el.dataset.f){S.lf[el.dataset.f]=el.value;S.lp=1;render();return}
 if(el.id==='dFrom'){S.from=el.value;S.lp=1;render();return}
 if(el.id==='dTo'){S.to=el.value;S.lp=1;render();return}
});
document.addEventListener('input',function(e){var el=e.target;if(el.id==='f-q'){var pos=el.selectionStart;S.lf.q=el.value;S.lp=1;render();var q=$('#f-q');if(q){q.focus();try{q.setSelectionRange(pos,pos)}catch(x){}}}});
document.addEventListener('mouseover',function(e){
 var b=e.target.closest('.bar');if(!b)return;var ro=$('#readout-ch');if(!ro)return;var i=+b.dataset.i;
 if(LIVE){var p=LS.sum&&LS.sum.series[i];if(p)ro.innerHTML='<b>'+esc(liveLabel(p.t,LS.sum.range))+'</b> · 전체 '+fmt(p.requests)+' · 5xx '+fmt(p.errors);return}
 ro.innerHTML='<b>'+HOURS[i]+'</b> · 전체 '+fmt(REQ[i])+' · 실패 '+fmt(FAIL[i])+' ('+(FAIL[i]/REQ[i]*100).toFixed(1)+'%)'});
window.addEventListener('hashchange',function(){var id=location.hash.slice(1);if(PAGES.some(function(p){return p.id===id})&&id!==S.page)go(id)});
var h0=location.hash.slice(1);if(PAGES.some(function(p){return p.id===h0}))S.page=h0;
render();
})();
