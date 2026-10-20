"""CI专属资源的精确用例清单；新用例/参数/原因须重新审查，不按模块或前缀放行。

固定SDK/3.10/真实捕获/CPU模型/素材不由托管CI下载；相应本机证明另存。
requests、numpy、PyYAML已经是dev依赖，不属于资源例外。
"""

RESOURCE_GROUPS = (
    ('tests.unit.development.test_voice_proposal_adapter',
     'explicit existing native repository required; never download',
     (
         'test_actual_native_buffer_reset_before_or_after_worker_keeps_same_verified_turn[True]',
         'test_actual_native_buffer_reset_before_or_after_worker_keeps_same_verified_turn[False]',
         'test_explicit_cancel_after_handoff_before_worker_never_revives_old_turn[explicit_reset]',
         'test_explicit_cancel_after_handoff_before_worker_never_revives_old_turn[abort]',
         'test_explicit_cancel_after_handoff_before_worker_never_revives_old_turn[continued]',
         'test_explicit_cancel_after_handoff_before_worker_never_revives_old_turn[close]',
         'test_tools_preflight_skips_before_any_candidate_rpc',
         'test_provider_preserves_all_methods_and_does_not_invent_functions',
         'test_pcm_prefix_change_invalidates_before_formal_reuse',
         'test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare[emotion]',
         'test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare[speaker]',
         'test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare[date]',
         'test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare[role]',
         'test_real_final_provider_changes_miss_and_do_not_repeat_formal_prepare[history]',
         'test_cancel_between_candidate_yield_and_native_enqueue_blocks_queues_store_and_history',
         'test_new_asr_turn_cannot_receive_previous_paused_answer',
         'test_unconfirmed_owned_close_keeps_slot_and_blocks_next_ticket',
         'test_snapshot_wait_does_not_reread_live_dialogue_after_worker_has_added_current_user',
         'test_pure_native_preview_preserves_speaker_projection_and_real_style_without_mutating_sets[False]',
         'test_pure_native_preview_preserves_speaker_projection_and_real_style_without_mutating_sets[True]',
         'test_native_preview_with_tools_skips_without_reading_live_dialogue_or_config',
         'test_new_audio_revokes_queued_output_and_background_put_before_sentence_id_changes',
         'test_actual_fast_reply_retires_candidate_and_never_archives_revoked_text[False]',
         'test_actual_fast_reply_retires_candidate_and_never_archives_revoked_text[True]',
         'test_native_dto_and_final_packet_sender_drop_old_output_after_new_speech',
         'test_confirmation_deadline_keeps_one_formal_fallback_and_retires_owned_request',
     )),
    ('tests.unit.development.test_voice_proposal_adapter_sdk',
     'explicit frozen AI ref/SDK/voice3.10/native repository required',
     (
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[reset_worker]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[metadata]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[speaker]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[date]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[role]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[history]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[pcm_changed]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[tools]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[yield_cancel]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[new_turn]',
         'test_actual_native_asr_adapter_and_python310_formal_sdk_rpc[queued_cancel]',
     )),
    ('tests.integration.test_voice_feedback_sdk',
     'explicit owner-installed fixed SDK required',
     (
         'test_actual_sdk_feedback_dict_preserves_session_scope_and_rejects_existing_candidate[False]',
         'test_actual_sdk_feedback_dict_preserves_session_scope_and_rejects_existing_candidate[True]',
     )),
    ('tests.integration.device_control.test_transport',
     '需要本机已安装的小智 Python 3.10 环境',
     (
         'test_real_http_and_upstream_mcp_with_simulated_device',
     )),
    ('tests.integration.memory_pipeline.test_xiaozhi_bridge',
     '固定上游源码未安装，其他协议回归仍可运行',
     (
         'test_real_upstream_dialogue_injects_context_if_available',
     )),
    ('tests.integration.memory_pipeline.test_xiaozhi_bridge',
     '小智 Python 3.10 环境未安装',
     (
         'test_python310_provider_calls_python312_worker_if_available',
     )),
    ('tests.integration.test_ab_hy_campus_gate_sdk',
     'explicit fixed SDK interpreter required',
     (
         'test_real_sdk_one_add_auto_evolve_stays_inside_persistent_hard_gate',
     )),
    ('tests.integration.test_ab_hy_provenance_replay',
     'explicit fixed SDK and existing captured responses required',
     (
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[original-correct]',
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[original-delete]',
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[guarded-correct]',
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[guarded-delete]',
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[upgrade-correct]',
         'test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence[upgrade-delete]',
     )),
    ('tests.integration.test_hy_background_gateway_combination',
     'explicit owner-installed fixed SDK required',
     (
         'test_actual_sdk_pending_advice_and_background_route_preserve_foreground_model_priority',
     )),
    ('tests.integration.test_hy_background_sdk',
     'explicit fixed SDK required',
     (
         'test_busy_advice_before_task_claim_and_actual_sdk_routes_only_evolve_background',
     )),
    ('tests.integration.test_hy_campus_transport',
     'explicit installed voice SDK/source required',
     (
         'test_actual_vendor_provider_and_python310_sdk_do_not_retry_and_drain_usage[200]',
         'test_actual_vendor_provider_and_python310_sdk_do_not_retry_and_drain_usage[400]',
     )),
    ('tests.integration.test_hy_daily_lifecycle',
     'explicit existing CPU BGE root required',
     (
         'test_existing_cpu_bge_and_constant_sdk_process_warm_recall',
     )),
    ('tests.integration.test_hy_daily_lifecycle',
     'explicit owner-installed SDK required',
     (
         'test_constant_identity_restart_shared_spend_and_owned_gateway_cleanup',
         'test_initialization_failure_releases_gateway_and_preserves_budget',
         'test_currency_proof_for_another_credential_cannot_start_or_charge',
         'test_campus_free_runtime_restart_recall_preserves_official_unknown',
         'test_verified_daily_management_create_reopen_profile_scope_and_bad_receipt_cleanup',
         'test_preexisting_daily_space_does_not_gain_profile_proof_from_new_receipt',
         'test_daily_requested_profile_injection_without_scope_fails_and_closes_owned_gateway',
     )),
    ('tests.integration.test_hy_layer_data_sdk',
     'explicit owner-installed fixed SDK required',
     (
         'test_real_sdk_all_layers_history_scoped_native_pages_details_no_writes_and_restart',
         'test_real_sdk_mock_extraction_raw_and_fact_read_without_further_model_calls',
         'test_real_sdk_profile_sources_follow_exact_sdk_merge_for_status_branch_null_and_empty',
         'test_real_sdk_incomplete_or_foreign_l0_never_returns_false_aggregate[scope_bad-profile_scope_unproven]',
         'test_real_sdk_incomplete_or_foreign_l0_never_returns_false_aggregate[profile_limit-profile_history_limit]',
         'test_real_sdk_graph_disabled_existing_marker_is_partial_not_empty_and_untouched',
         'test_real_sdk_l0_without_trusted_scope_stamp_is_unavailable_not_zero',
     )),
    ('tests.integration.test_hy_memory_gateway',
     'isolated SDK missing',
     (
         'test_sdk_local_gateway_has_shared_budget_and_embedding_scope',
     )),
    ('tests.integration.test_hy_memory_management_rpc',
     'owner-installed SDK required',
     (
         'test_real_process_management_permissions_update_delete_and_restart',
         'test_profile_scope_is_created_only_for_trusted_fresh_space_and_rechecked',
         'test_real_sdk_full_node_audit_update_raw_preservation_and_chain_delete_effects',
     )),
    ('tests.integration.test_hy_memory_sdk_offline',
     'owner-installed isolated Hy environment missing',
     (
         'test_real_sdk_network_denied_failure_and_source_persistence',
         'test_real_sdk_simulated_models_management_recall_and_restart',
         'test_real_sdk_commit_before_platform_receipt_is_uncertain',
         'test_real_sdk_per_question_clone_protocol_isolation',
     )),
    ('tests.integration.test_hy_release_management',
     'explicit owner-installed SDK required',
     (
         'test_real_http_sdk_correction_source_replay_pause_and_isolated_delete',
         'test_real_sdk_readback_failure_remains_uncertain_after_restart',
     )),
    ('tests.integration.test_hy_roundscreen_sdk',
     'explicit existing Hy and voice interpreters required',
     (
         'test_python310_real_provider_to_http312_and_real_hy_sdk',
     )),
    ('tests.integration.test_hy_roundscreen_sdk',
     'explicit owner-installed Hy interpreter required',
     (
         'test_real_sdk_deferred_round_completion_recall_and_restart',
         'test_actual_runtime_version_mismatch_rejects_and_releases_both_owners',
         'test_optional_profile_add_and_search_observations_share_scope_without_extra_model_calls',
         'test_real_sdk_context_reaches_synthetic_answer_and_assistant_archive_separately',
     )),
    ('tests.integration.test_hy_semantic_platform_sdk',
     'explicit owner-installed fixed SDK required',
     (
         'test_actual_sdk_nonempty_candidate_formal_context_claim_and_native_http_errors[projection-True]',
         'test_actual_sdk_nonempty_candidate_formal_context_claim_and_native_http_errors[normal-False]',
     )),
    ('tests.integration.test_hy_semantic_sdk',
     'explicit owner-installed fixed SDK required',
     (
         'test_real_native_evolve_graph_content_sources_restart_and_readonly_intention',
         'test_real_unverified_profile_intention_formal_candidate_labels_and_batch_capture_diagnostics',
         'test_native_background_does_not_hold_foreground_rpc_and_correction_isolates_old_derivatives[slow]',
         'test_native_background_does_not_hold_foreground_rpc_and_correction_isolates_old_derivatives[blocked_write_loop]',
         'test_real_runtime_management_readback_then_rederive_preserves_correction_sources',
         'test_real_sdk_owner_termination_preserves_uncertain_task_without_automatic_replay',
         'test_candidate_snapshot_is_native_readonly_and_invalidates_for_background_and_restart',
         'test_real_nonempty_profile_candidate_matches_formal_prepare_content_and_sources[False]',
         'test_real_nonempty_profile_candidate_matches_formal_prepare_content_and_sources[True]',
         'test_real_pro_source_enable_semantic_reopen_rollback_preserves_source_graph_and_tasks',
         'test_real_pre_fix_semantic_source_alias_reopens_without_identity_rewrite',
     )),
    ('tests.integration.test_voice_proposal_sdk_rpc',
     'explicit fixed SDK and owner voice 3.10 required',
     (
         'test_actual_sdk_and_cross_python_rpc_adopts_only_same_formal_memory_and_policy[projection-False-True]',
         'test_actual_sdk_and_cross_python_rpc_adopts_only_same_formal_memory_and_policy[normal-False-False]',
         'test_actual_sdk_and_cross_python_rpc_adopts_only_same_formal_memory_and_policy[projection-True-False]',
         'test_actual_sdk_and_formal_http_bind_raw_asr_message_separately_from_query[none]',
         'test_actual_sdk_and_formal_http_bind_raw_asr_message_separately_from_query[metadata]',
         'test_actual_sdk_and_formal_http_bind_raw_asr_message_separately_from_query[tools]',
     )),
    ('tests.unit.development.test_ad_cosy_benchmark',
     'owner-installed voice interpreter unavailable',
     (
         'test_real_http_client_reaches_cancel_boundary_then_plays_new_round[buffered-None]',
         'test_real_http_client_reaches_cancel_boundary_then_plays_new_round[adaptive-None]',
         'test_real_http_client_reaches_cancel_boundary_then_plays_new_round[adaptive-before_audio]',
         'test_real_http_client_reaches_cancel_boundary_then_plays_new_round[adaptive-buffering]',
         'test_real_http_client_reaches_cancel_boundary_then_plays_new_round[adaptive-after_audio]',
     )),
    ('tests.unit.development.test_ad_cosy_http_opus',
     'owner-installed voice interpreter unavailable',
     (
         'test_adaptive_real_http_fir_opus_eos_and_cancel_next_turn[False-16000]',
         'test_adaptive_real_http_fir_opus_eos_and_cancel_next_turn[False-24000]',
         'test_adaptive_real_http_fir_opus_eos_and_cancel_next_turn[True-16000]',
         'test_adaptive_real_http_fir_opus_eos_and_cancel_next_turn[True-24000]',
     )),
    ('tests.unit.development.test_cosyvoice_acceleration',
     'explicit existing CPU torch runtime required',
     (
         'test_real_cpu_module_replacement_preserves_registered_original',
         'test_real_cpu_quantization_keeps_baseline_and_checks_ranking',
     )),
    ('tests.unit.development.test_cosyvoice_continuous_pcm',
     'owner-installed voice interpreter unavailable',
     (
         'test_continuous_fir_matches_whole_reference_and_real_opus_frames',
     )),
    ('tests.unit.development.test_cosyvoice_stream_benchmark',
     'owner-installed voice interpreter unavailable',
     (
         'test_real_client_benchmark_preserves_daily_segmentation_and_exact_frames[buffered-False]',
         'test_real_client_benchmark_preserves_daily_segmentation_and_exact_frames[buffered-True]',
         'test_real_client_benchmark_preserves_daily_segmentation_and_exact_frames[incremental-False]',
         'test_real_client_benchmark_preserves_daily_segmentation_and_exact_frames[incremental-True]',
     )),
    ('tests.unit.development.test_cosyvoice_stream_runtime',
     'owner-installed Cosy interpreter unavailable',
     (
         'test_installed_python310_accepts_exact_contract_without_cuda_initialization',
     )),
    ('tests.unit.development.test_hy_campus_latency_probe',
     'existing owner-installed SDK required; no installation',
     (
         'test_two_source_real_sdk_local_upstream_isolated_roots_and_safe_receipts',
         'test_first_failure_or_unknown_stops_both_arms_without_retry[http_error]',
         'test_first_failure_or_unknown_stops_both_arms_without_retry[missing_usage]',
         'test_first_failure_or_unknown_stops_both_arms_without_retry[disconnect]',
         'test_hard_cap_blocks_extraction_after_first_answer_before_second_provider_post',
         'test_bad_second_proof_refused_before_any_request_and_output_creation',
     )),
    ('tests.unit.development.test_hy_windows_owned_processes',
     'existing owner-installed SDK metadata only; no installation',
     (
         'test_real_windows_sdk_metadata_stdout_and_exit_code',
     )),
    ('tests.unit.development.test_local_config_layout',
     'host does not grant synthetic symlink creation',
     (
         'test_migration_rejects_escape_and_symlink',
     )),
    ('tests.unit.development.test_voice_proposal_rpc',
     'explicit frozen AF host commit required; no dirty worktree imports',
     (
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_complete]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_headers_cancel]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_body_cancel]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_fresh_miss]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_source_miss]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_revised_cleanup]',
         'test_actual_frozen_af_host_over_rpc_keeps_all_six_memory_items_and_owned_ack[real_host_new_turn_cleanup]',
     )),
    ('tests.unit.development.test_voice_proposal_rpc',
     'explicit installed Python3.10 required for two-process contract test',
     (
         'test_real_python310_client_and_host_subprocess_roundtrip_with_nonempty_context',
         'test_ambiguous_start_never_retries_and_retains_slot_until_scoped_cancel_ack[slow_start]',
         'test_ambiguous_start_never_retries_and_retains_slot_until_scoped_cancel_ack[disconnect_start]',
         'test_ambiguous_start_never_retries_and_retains_slot_until_scoped_cancel_ack[leak_start]',
         'test_cancel_late_epoch_and_miss_cannot_publish_old_answer[slow_confirm]',
         'test_cancel_late_epoch_and_miss_cannot_publish_old_answer[epoch_race]',
         'test_cancel_late_epoch_and_miss_cannot_publish_old_answer[bad_confirm]',
         'test_unconfirmed_or_false_provider_guarantee_keeps_compute_slot[closing]',
         'test_unconfirmed_or_false_provider_guarantee_keeps_compute_slot[bad_ack]',
         'test_bad_transport_response_cannot_redirect_or_start_model[redirect]',
         'test_bad_transport_response_cannot_redirect_or_start_model[bad_json]',
         'test_bad_transport_response_cannot_redirect_or_start_model[chunked]',
         'test_tools_required_is_a_miss_and_never_prepares_model',
         'test_rejected_runtime_auth_does_not_start_or_retry_candidate',
         'test_large_nonempty_memory_json_body_is_not_limited_by_header_buffer',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_json]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_effective]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_metadata_changed]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_speaker_changed]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_missing_current]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_context_changed]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_tools_present]',
         'test_real_python310_v2_keeps_asr_payload_and_effective_boundary_gates[v2_effective_tools]',
     )),
    ('tests.unit.development.test_voice_proposal_sdk_input',
     'explicit fixed AI ref, owner-installed SDK and Python3.10 required',
     (
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[none]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[metadata]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[speaker]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[current]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[history]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[date]',
         'test_real_sdk_formal_routes_and_python310_preserve_effective_input[tools]',
     )),
    ('tests.unit.development.test_voice_waiting_handoff',
     'owner-installed pinned upstream source absent',
     (
         'test_pinned_upstream_scheduler_stops_spending_slots_on_discarded_cue_tail',
     )),
    ('tests.unit.entrypoints.test_otto_preview_api',
     '当前 Windows 会话未允许创建测试符号链接',
     (
         'test_link_escape_rejected',
     )),
    ('tests.unit.entrypoints.test_otto_preview_api',
     '真实资源只在显式绑定允许的固定目录时检查',
     (
         'test_explicit_fixed_input',
     )),
    ('tests.unit.infrastructure.test_round_wallpaper_library',
     '本机未安装用户提供的 FFmpeg',
     (
         'test_library_real_ffmpeg_roundtrip_when_local_tools_exist',
     )),
    ('tests.unit.methods.test_hy_recall_stage_probe',
     'existing isolated SDK source absent; no installation',
     (
         'test_known_sdk_tree_is_read_only_pinned_without_importing_sdk',
     )),
)


def declared_skips():
    result = {}
    def add(module, name, reason):
        key = (module, name)
        if key in result:
            raise ValueError('duplicate CI resource declaration')
        result[key] = reason
    for module, reason, names in RESOURCE_GROUPS:
        for name in names:
            add(module, name, reason)
    # 固定SDK源码逐函数对照的49项；长字符串参数仍逐字匹配，不能用前缀通配。
    # 保留显式输入组合，避免把数万字符的pytest ID重复抄进静态清单。
    module = 'tests.unit.methods.test_short_embedding_input'
    reason = 'fixed SDK source is not installed in this worktree'
    short = ('', 'hello', r'\u4f60\u597d\uff0c\u5706\u5c4f\u3002',
             r'Hello\uff0c\u5706\u5c4f123', '<|endoftext|>', 'a' * 8128, r'\u4e2d' * 2709 + 'a', r'\ud800')
    unusual = ('a' * 8129 + '-8128', r'\u4e2d' * 2710 + '-8128', 'abc-0', 'abc--1',
               'abc-None', 'abc-8', 'abc-1.5', 'abc-True', 'None-8128', '123-8128', 'abc-2')
    for unavailable in ('False', 'True'):
        for value in short:
            add(module, f'test_matches_original_for_short_boundary_empty_and_invalid_unicode[{unavailable}-{value}]', reason)
        for value in unusual:
            add(module, f'test_unsafe_inputs_and_unusual_limits_keep_original_guard[{unavailable}-{value}]', reason)
    for value in ('version', 'limit', 'fallback', 'stats', 'filename', 'hash', 'wrapped'):
        add(module, f'test_incompatible_sdk_is_left_untouched[{value}]', reason)
    for name in ('test_short_path_never_loads_encoder_and_keeps_original_counters',
                 'test_disabled_mode_and_double_install_do_not_replace_existing_function',
                 'test_close_detects_lost_wrapper_ownership',
                 'test_delegated_exception_is_not_swallowed_and_is_counted'):
        add(module, name, reason)
    return result
