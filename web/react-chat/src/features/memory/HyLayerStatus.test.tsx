import {expect,test} from 'vitest';
import {render,screen,within} from '@testing-library/react';
import {graphPage,layerPage,semanticRecord} from '../../tests/fixtures/hyLayerData';
import {semanticStatusFixture,disabledSemanticStatus} from '../../tests/fixtures/hySemantic';
import {capabilityFixture} from '../../tests/fixtures/hyCapabilityView';
import {hyCapabilityView} from './hyCapabilityView';
import {HyLayerStatus} from './HyLayerStatus';

test('配置关闭、已有存量、图部分覆盖和未知实例证据独立，开关不会提升能力',()=>{
  const page=layerPage('l6_schema',{coverage:'vdb_only_graph_unopened',read_status:'partial',total:null});
  const view=hyCapabilityView(page);
  expect(view.expected.state).toBe('disabled');expect(view.coverage.state).toBe('partial');
  expect(view.instance.state).toBe('unknown');expect(view.background.state).toBe('unknown');expect(view.management.state).toBe('unknown');
  render(<HyLayerStatus page={page} runtimeSnapshot={{runtime:{write_enabled:true,use_enabled:true},observed_at:'2026-10-21T04:00:00Z',stale:false}}/>);
  expect(screen.getByText(/本次运行开关快照：写入开启，回答使用开启/)).toBeTruthy();
  expect(screen.getByText(/原生最后更新时间尚未提供/)).toBeTruthy();expect(screen.queryByText('已启用',{exact:true})).toBeNull();
  expect(screen.getByText('逐层只读成功不能证明纠正、删除或后台写入已获准。')).toBeTruthy();
});

test('已配置和已有记录都不证明后台生成成功',()=>{
  const view=hyCapabilityView(layerPage('l7_intention',{generation_state:'configured'}));
  expect(view.expected.state).toBe('configured');expect(view.instance.state).toBe('unknown');expect(view.background.state).toBe('unknown');
  expect(view.coverage.state).toBe('present');expect(view.expected.description).toContain('尚不能证明');
});

test('精确空范围、图未读空页和不可读的区别保持到视图',()=>{
  expect(hyCapabilityView(layerPage('l7_intention',{items:[],data_state:'empty',total:0})).coverage.state).toBe('empty');
  expect(hyCapabilityView(layerPage('l7_intention',{items:[],data_state:'unknown',read_status:'partial',coverage:'vdb_only_graph_unopened',total:null})).coverage.state).toBe('partial');
  expect(hyCapabilityView(layerPage('l7_intention',{items:[],data_state:'unknown',read_status:'unavailable',coverage:'unavailable',total:null,has_more:null})).coverage.state).toBe('blocked');
});

test('可插拔合成视图分别显示实例启用、后台任务、覆盖和管理阻断，不出现修改按钮',()=>{
  render(<HyLayerStatus page={layerPage('l7_intention')} capabilities={capabilityFixture()}/>);
  const panel=screen.getByLabelText('分层接入与运行证据');
  for(const name of ['期望配置','实例实际能力','证据与条目覆盖','后台任务','管理可用性'])expect(within(panel).getByText(name)).toBeTruthy();
  expect(within(panel).getByText('已启用',{exact:true})).toBeTruthy();expect(within(panel).getByText('运行中',{exact:true})).toBeTruthy();
  expect(within(panel).getByText('受限',{exact:true})).toBeTruthy();expect(within(panel).queryAllByRole('button')).toHaveLength(0);
});

test('过期运行开关和能力失败不能当作新鲜成功；不支持与未启用分别显示',()=>{
  const fixture=capabilityFixture({instance:{state:'unsupported',description:'合成实例无该能力',observed_at:null},background:{state:'failed',description:'合成任务失败',observed_at:null},management:{state:'disabled',description:'合成管理关闭',observed_at:null}});
  render(<HyLayerStatus page={layerPage('l6_schema')} capabilities={fixture} runtimeSnapshot={{runtime:{write_enabled:false,use_enabled:true},observed_at:'2026-10-21T04:00:00Z',stale:true}}/>);
  expect(screen.getByText('不支持',{exact:true})).toBeTruthy();expect(screen.getByText('失败',{exact:true})).toBeTruthy();expect(screen.getByText('未启用',{exact:true})).toBeTruthy();
  expect(screen.getByText(/上次运行开关快照：写入暂停/)).toBeTruthy();
});

test('普通层不增加L6/L7能力界面',()=>{
  render(<HyLayerStatus page={layerPage('l2_fact')}/>);expect(screen.queryByLabelText('分层接入与运行证据')).toBeNull();
});

test('实际实例与期望配置分开，隔离空图不投影成无条目或关闭',()=>{
  const page=graphPage({items:[],data_state:'empty',total:0});
  const status=semanticStatusFixture({schema_state:'isolated',epoch:2,ready_epoch:1,management_available:false,task_counts:{running:1},paused:true});
  const view=hyCapabilityView(page,status);
  expect(view.instance.state).toBe('enabled');expect(view.coverage.state).toBe('isolated');expect(view.background.state).toBe('running');expect(view.management.state).toBe('blocked');
  render(<HyLayerStatus page={page} semanticSnapshot={status}/>);
  expect(screen.getByText('派生已隔离',{exact:true})).toBeTruthy();expect(screen.queryByText('无条目',{exact:true})).toBeNull();
  expect(screen.getByText(/未认领任务暂停/)).toBeTruthy();expect(screen.getByText(/执行与主动联系均未授权/)).toBeTruthy();
});

test('disabled实际结构保留未知任务计数，已保存语义更新时间不被读取时间取代',()=>{
  render(<HyLayerStatus page={graphPage({items:[semanticRecord('l6_schema')]})} semanticSnapshot={disabledSemanticStatus()}/>);
  expect(screen.getByText(/未返回的任务状态计数保持未知，不补零/)).toBeTruthy();
  expect(screen.getByText(/逐条原生更新时间见记录/)).toBeTruthy();
  expect(screen.getByLabelText('延迟测量证据状态').textContent).toContain('尚无统一阶段测量证据');
});

test('只有pending不能标为运行，缺运行计数也不猜空闲',()=>{
  expect(hyCapabilityView(graphPage(),semanticStatusFixture({task_counts:{pending:1}})).background.state).toBe('pending');
  expect(hyCapabilityView(graphPage(),semanticStatusFixture({task_counts:{completed:1}})).background.state).toBe('unknown');
  expect(hyCapabilityView(graphPage(),semanticStatusFixture({task_counts:{pending:1},paused:true})).background.state).toBe('paused');
});
