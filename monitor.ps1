# Live Trading Bot Monitor - Real-time Status Dashboard
# Run with: .\monitor.ps1

function Get-BotStatus {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5003/api/status" -UseBasicParsing
        return $response.Content | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Format-Currency {
    param([double]$Value)
    if ($Value -ge 0) {
        return "$$($Value.ToString('F2'))" 
    } else {
        return "-$$($Value.ToString('F2'))"
    }
}

function Format-Percentage {
    param([double]$Value)
    return "$($Value.ToString('F1'))%"
}

Clear-Host
$startTime = Get-Date
$lastProfit = 0
$lastTrades = 0

while ($true) {
    Clear-Host
    $statusData = Get-BotStatus
    
    if ($null -eq $statusData) {
        Write-Host "❌ Cannot connect to bot API" -ForegroundColor Red
        Write-Host "Make sure bot_api.py is running on port 5003" -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        continue
    }
    
    $s = $statusData.status
    $uptime = (Get-Date) - $startTime
    $uptimeStr = "$($uptime.Hours)h $($uptime.Minutes)m $($uptime.Seconds)s"
    
    # Header
    Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║        🤖 ARBITRAGE BOT - LIVE TRADING MONITOR 🤖             ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    # Status
    Write-Host ""
    Write-Host "📍 BOT STATUS" -ForegroundColor Green
    Write-Host "├─ Status: " -NoNewline
    if ($s.running -eq $true) {
        Write-Host "🟢 RUNNING" -ForegroundColor Green
    } else {
        Write-Host "🔴 STOPPED" -ForegroundColor Red
    }
    Write-Host "├─ Mode: $($s.execution_mode.ToUpper())" -ForegroundColor White
    Write-Host "├─ Trade Mode: $($s.trade_execution_mode.ToUpper()) (Capital + Flash)" -ForegroundColor White
    Write-Host "└─ Uptime: $uptimeStr" -ForegroundColor White
    
    # Profitability
    Write-Host ""
    Write-Host "💰 PROFITABILITY" -ForegroundColor Green
    $netProfit = $s.cycle_profit - $s.cycle_loss
    Write-Host "├─ Gross Profit: " -NoNewline
    Write-Host (Format-Currency $s.cycle_profit) -ForegroundColor Green
    Write-Host "├─ Losses: " -NoNewline
    Write-Host (Format-Currency $s.cycle_loss) -ForegroundColor Red
    Write-Host "├─ Net P&L: " -NoNewline
    if ($netProfit -ge 0) {
        Write-Host (Format-Currency $netProfit) -ForegroundColor Green
    } else {
        Write-Host (Format-Currency $netProfit) -ForegroundColor Red
    }
    Write-Host "└─ Withdrawable: " -NoNewline
    Write-Host (Format-Currency $s.withdrawable) -ForegroundColor Yellow
    
    # Trade Statistics
    Write-Host ""
    Write-Host "📈 TRADES EXECUTED" -ForegroundColor Green
    $tradeDelta = $s.total_trades - $lastTrades
    Write-Host "├─ Capital Trades: $($s.triangle_trades) (regular with your USDT)" -ForegroundColor White
    Write-Host "├─ Flash Loan Trades: $($s.flash_loan_trades) (borrowed capital)" -ForegroundColor Cyan
    Write-Host "├─ Total Trades: $($s.total_trades)" -NoNewline
    if ($tradeDelta -gt 0) {
        Write-Host " (+$tradeDelta)" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "├─ Failed Trades: " -NoNewline
    if ($s.failed_trades -gt 0) {
        Write-Host "$($s.failed_trades)" -ForegroundColor Red
    } else {
        Write-Host "$($s.failed_trades)" -ForegroundColor Green
    }
    Write-Host "└─ Win Rate: " -NoNewline
    if ($s.total_trades -gt 0) {
        $winRate = (($s.total_trades - $s.failed_trades) / $s.total_trades) * 100
        Write-Host (Format-Percentage $winRate) -ForegroundColor Green
    } else {
        Write-Host "N/A" -ForegroundColor Gray
    }
    
    # Gas Usage
    Write-Host ""
    Write-Host "⛽ GAS USAGE" -ForegroundColor Green
    Write-Host "├─ Used: $(Format-Currency $s.gas_usage_usd) / $(Format-Currency $s.gas_usage_limit)" -ForegroundColor White
    Write-Host "├─ Usage: " -NoNewline
    $gasBar = ""
    $gasPct = [int]$s.gas_usage_pct
    for ($i = 0; $i -lt 20; $i++) {
        if ($i -lt ($gasPct / 5)) {
            $gasBar += "█"
        } else {
            $gasBar += "░"
        }
    }
    Write-Host "$gasBar " -NoNewline
    if ($gasPct -lt 50) {
        Write-Host (Format-Percentage $s.gas_usage_pct) -ForegroundColor Green
    } elseif ($gasPct -lt 80) {
        Write-Host (Format-Percentage $s.gas_usage_pct) -ForegroundColor Yellow
    } else {
        Write-Host (Format-Percentage $s.gas_usage_pct) -ForegroundColor Red
    }
    Write-Host "└─ Current Gas: $($s.gas_gwei.ToString('F2')) gwei" -ForegroundColor White
    
    # Capital
    Write-Host ""
    Write-Host "💵 CAPITAL STATUS" -ForegroundColor Green
    Write-Host "├─ Starting Capital: $(Format-Currency $s.starting_capital)" -ForegroundColor White
    Write-Host "├─ Current Capital: $(Format-Currency $s.subscription_capital)" -ForegroundColor White
    Write-Host "└─ Profit Margin: " -NoNewline
    if ($s.starting_capital -gt 0) {
        $margin = (($netProfit / $s.starting_capital) * 100)
        Write-Host (Format-Percentage $margin) -ForegroundColor Green
    } else {
        Write-Host "N/A" -ForegroundColor Gray
    }
    
    # Cycle Info
    Write-Host ""
    Write-Host "🔄 CYCLE INFO" -ForegroundColor Green
    Write-Host "├─ Cycle Start: $($s.cycle_start.Substring(0, 19))" -ForegroundColor White
    Write-Host "├─ Cycle End: $($s.cycle_end.Substring(0, 19))" -ForegroundColor White
    Write-Host "├─ Time Remaining: $($s.cycle_remaining_seconds)s" -ForegroundColor White
    Write-Host "└─ Scan Interval: $($s.engine_scan_interval_seconds)s (next scan in $($s.engine_next_scan_seconds)s)" -ForegroundColor White
    
    # Recent Trades
    if ($s.recent_trades -and $s.recent_trades.Count -gt 0) {
        Write-Host ""
        Write-Host "🚀 RECENT TRADES (Last 5)" -ForegroundColor Green
        $recentCount = [Math]::Min(5, $s.recent_trades.Count)
        $lastTrades = $s.recent_trades[-$recentCount..-1]
        foreach ($trade in $lastTrades) {
            $profitStr = if ($trade.profit -ge 0) { 
                "$(Format-Currency $trade.profit)" 
            } else { 
                "$(Format-Currency $trade.profit)" 
            }
            $modeStr = if ($trade.type -eq "flash_loan") { "⚡ FLASH" } else { "💵 CAPITAL" }
            Write-Host "├─ $($trade.pair) on $($trade.buyOn) → $($trade.sellOn)" -ForegroundColor White
            Write-Host "│  $modeStr | Profit: $profitStr | Gas: $(Format-Currency $trade.gas_cost)" -ForegroundColor Cyan
        }
    }
    
    # Live Arm Status
    Write-Host ""
    Write-Host "🔐 LIVE TRADING STATUS" -ForegroundColor Green
    Write-Host "├─ Live Trading Enabled: " -NoNewline
    if ($s.live_trading_enabled -eq $true) {
        Write-Host "✅ YES" -ForegroundColor Green
    } else {
        Write-Host "❌ NO" -ForegroundColor Red
    }
    Write-Host "├─ Armed Until: " -NoNewline
    if ($s.live_armed_until) {
        Write-Host "$($s.live_armed_until.Substring(0, 19))" -ForegroundColor Cyan
    } else {
        Write-Host "Not Armed" -ForegroundColor Yellow
    }
    Write-Host "└─ Arm Remaining: $($s.live_armed_remaining_seconds)s" -ForegroundColor White
    
    # Footer
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "Last Updated: $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Gray
    Write-Host "Refresh in 5 seconds... (Press Ctrl+C to exit)" -ForegroundColor Gray
    Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    
    Start-Sleep -Seconds 5
}
