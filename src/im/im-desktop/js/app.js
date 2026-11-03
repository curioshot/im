/**
 * im - Internet Monitor Desktop App
 * Frontend JavaScript - Stitch Design System
 */

(function() {
  'use strict';

  // Design System Colors (matching CSS variables)
  var COLORS = {
    bg: '#1a1a2e',
    surface: '#16213e',
    surface_bright: '#0c0c1f',
    surface_container: '#1a1a2e',
    surface_container_high: '#28283d',
    text_primary: '#e2e0fc',
    text_secondary: '#c0c7d1',
    text_muted: '#7f8c8d',
    accent_primary: '#64b5f6',
    accent_success: '#4caf50',
    accent_warning: '#ff9800',
    accent_error: '#f44336',
    border: '#37474f',
    focus_ring: '#64b5f6',
  };

  // State
  var state = {
    status: 'Starting...',
    latency: null,
    down: null,
    up: null,
    packet_loss: 0,
    devices: [],
    checks_list: [],
  };

  // DOM Elements
  var elements = {
    statusText: document.getElementById('status-text'),
    statusDot: document.getElementById('status-dot'),
    downValue: document.getElementById('down-val'),
    uploadValue: document.getElementById('up-val'),
    lossValue: document.getElementById('loss-val'),
    timelineCanvas: document.getElementById('timeline-canvas'),
    devicesTable: document.getElementById('devices-table-body'),
    checksTable: document.getElementById('checks-table-body'),
  };

  /**
   * Initialize the app
   */
  function init() {
    loadData();
    setInterval(loadData, 1000);
  }

  /**
   * Load data from the local state file
   */
  async function loadData() {
    try {
      var response = await fetch('data/status.json', { cache: 'no-store' });
      if (response.ok) {
        var data = await response.json();
        applyData(data);
      }
    } catch (e) {
      // Silently fail - data file may not exist yet
    }
  }

  /**
   * Apply data to state
   */
  function applyData(data) {
    state.status = data.status || 'OFFLINE';
    state.latency = data.latency || null;
    state.download = data.download || null;
    state.upload = data.upload || null;
    state.packet_loss = data.packet_loss || 0;
    state.devices = data.devices || [];
    state.checks_list = data.checks_list || [];
    
    render();
  }

  /**
   * Render the UI
   */
  function render() {
    // Status indicator
    elements.statusText.textContent = state.status;
    elements.statusDot.className = 'status-dot';
    elements.statusDot.classList.add(state.status === 'Online' ? 'online' : 'offline');

    // Stats cards
    if (state.latency !== null && state.latency !== undefined) {
      elements.latencyValue.textContent = state.latency.toFixed(1) + ' ms';
    }
    if (state.download !== null && state.download !== undefined) {
      elements.downloadValue.textContent = state.download.toFixed(1) + ' Mbps';
    }
    if (state.upload !== null && state.upload !== undefined) {
      elements.uploadValue.textContent = state.upload.toFixed(1) + ' Mbps';
    }
    if (state.packet_loss !== null && state.packet_loss !== undefined) {
      elements.lossValue.textContent = state.packet_loss.toFixed(1) + ' %';
    }

    // Update timeline
    updateTimeline();

    // Update devices table
    updateDevicesTable();

    // Update checks table
    updateChecksTable();
  }

  /**
   * Update timeline chart
   */
  function updateTimeline() {
    var canvas = document.getElementById('timeline-canvas');
    var ctx = canvas.getContext('2d');
    
    var width = canvas.width;
    var height = canvas.height;
    
    ctx.clearRect(0, 0, width, height);
    
    // Draw axis lines
    ctx.strokeStyle = COLORS.border;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(40, 10);
    ctx.lineTo(40, height - 30);
    ctx.lineTo(width - 10, height - 30);
    ctx.stroke();
    
    var samples = state.checks_list.slice(-30);
    if (samples.length < 2) return;
    
    var maxLatency = 0;
    for (var i = 0; i < samples.length; i++) {
      var lat = samples[i][1];
      if (lat !== null && lat !== undefined && lat > maxLatency) {
        maxLatency = lat;
      }
    }
    if (maxLatency === 0) maxLatency = 100;
    
    var x_step = (width - 50) / (samples.length - 1);
    
    var points = [];
    for (var i = 0; i < samples.length; i++) {
      var up = samples[i][0];
      var lat = samples[i][1];
      var x = 40 + i * x_step;
      var y;
      if (lat !== null && lat !== undefined) {
        y = height - 30 - (lat / max_latency) * (height - 40);
      } else {
        y = height - 30;
      }
      points.push([x, y]);
    }
    
    // Draw line
    ctx.strokeStyle = COLORS.accent_primary;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (var i = 1; i < points.length; i++) {
      ctx.lineTo(points[i][0], points[i][1]);
    }
    ctx.stroke();
    
    // Draw points
    for (var i = 0; i < points.length; i++) {
      var x = points[i][0];
      var y = points[i][1];
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.accent_primary;
      ctx.fill();
    }
  }

  /**
   * Update devices table
   */
  function updateDevicesTable() {
    var tbody = document.getElementById('devices-table-body');
    tbody.innerHTML = '';
    
    if (!state.devices || state.devices.length === 0) {
      var row = document.createElement('tr');
      row.innerHTML = '<td colspan="4" style="text-align: center; color: #7f8c8d;">No devices found</td>';
      tbody.appendChild(row);
      return;
    }
    
    state.devices.forEach(function(entry) {
      var row = document.createElement('tr');
      row.innerHTML = '<td>' + (entry.ip || '-') + '</td>' +
                      '<td>' + (entry.mac || '-') + '</td>' +
                      '<td><span class="badge status-' + (entry.state === 'REACHABLE' ? 'online' : 'offline') + '">' + entry.state + '</span></td>' +
                      '<td>' + (entry.first || '-') + '</td>';
      tbody.appendChild(row);
    });
  }

  /**
   * Update checks table
   */
  function updateChecksTable() {
    var tbody = document.getElementById('checks-table-body');
    tbody.innerHTML = '';
    
    if (!state.checks_list || state.checks_list.length === 0) {
      var row = document.createElement('tr');
      row.innerHTML = '<td colspan="3" style="text-align: center; color: #7f8c8d;">No checks yet</td>';
      tbody.appendChild(row);
      return;
    }
    
    state.checks_list.forEach(function(check) {
      var time = new Date(check[0] * 1000).toLocaleTimeString();
      var statusClass = check[0] ? 'status-online' : 'status-error';
      var statusText = check[0] ? 'Online' : 'Offline';
      
      var row = document.createElement('tr');
      row.innerHTML = '<td>' + time + '</td>' +
                      '<td><span class="badge ' + statusClass + '">' + statusText + '</span></td>' +
                      '<td>' + (check[1] ? check[1] + ' ms' : 'N/A') + '</td>';
      tbody.appendChild(row);
    });
  }

  // Initialize on load
  document.addEventListener('DOMContentLoaded', init);
})();