import {Button as AstryxButton, type ButtonProps} from '@astryxdesign/core/Button';

/** 保留表单和设备命令对原生 disabled 的约束，键盘提交也不能触发锁定操作。 */
export function Button(props: ButtonProps) {
  const native = {disabled: Boolean(props.isDisabled || props.isLoading)};
  return <AstryxButton {...native} {...props}/>;
}
