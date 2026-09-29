// TrendEnsemblePortfolio: cBot de seguimiento de tendencia para cTrader.
//
// Es la versión para cTrader de la estrategia `trend_ensemble` de
// scripts/trend_strategies.py con objetivo de volatilidad por activo y de
// cartera (la configuración validada en el backtest de Python):
//
//   1. Señal por símbolo: media de 4 cruces de EMAs sobre cierres diarios
//      (8/32, 16/64, 32/128, 64/256). 1 voto por par alcista; de 0 a 1
//      (de -1 a 1 si se permiten cortos).
//   2. Paridad de riesgo: peso = señal * volObjetivoActivo / volatilidad
//      (media exponencial de 32 días), limitado a ApalancamientoMaxActivo,
//      y dividido entre el número de símbolos.
//   3. Objetivo de volatilidad de cartera: todos los pesos se escalan por
//      un mismo factor con una matriz de covarianzas exponencial, sin que la
//      exposición bruta pase de ExposicionBrutaMax.
//   4. Una vez por día (al cerrar la vela diaria) se recalculan los pesos y
//      cada posición solo se ajusta si se aleja del objetivo más que el
//      umbral de rebalanceo. Las órdenes de cada símbolo se envían cuando su
//      mercado está abierto.
//
// Uso: añade este archivo como cBot en cTrader (Automate), compílalo y
// ejecútalo en cualquier gráfico. Pon en "Símbolos" la lista separada por
// comas con los nombres de tu bróker (vacío = símbolo del gráfico). Empieza
// con "Solo simular" activado y revisa el registro antes de operar.

using System;
using System.Collections.Generic;
using System.Linq;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None, TimeZone = TimeZones.UTC)]
    public class TrendEnsemblePortfolio : Robot
    {
        [Parameter("Símbolos (separados por comas)", DefaultValue = "", Group = "Cartera")]
        public string SymbolList { get; set; }

        [Parameter("Etiqueta de las posiciones", DefaultValue = "TrendEnsemble", Group = "Cartera")]
        public string Label { get; set; }

        [Parameter("Permitir cortos", DefaultValue = false, Group = "Cartera")]
        public bool AllowShort { get; set; }

        [Parameter("Volatilidad objetivo por activo", DefaultValue = 0.15, MinValue = 0.01, MaxValue = 1, Group = "Riesgo")]
        public double AssetTargetVol { get; set; }

        [Parameter("Apalancamiento máx. por activo", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Group = "Riesgo")]
        public double AssetMaxLeverage { get; set; }

        [Parameter("Volatilidad objetivo de la cartera", DefaultValue = 0.10, MinValue = 0.01, MaxValue = 1, Group = "Riesgo")]
        public double PortfolioTargetVol { get; set; }

        [Parameter("Exposición bruta máx. de la cartera", DefaultValue = 1.0, MinValue = 0.1, MaxValue = 10, Group = "Riesgo")]
        public double MaxGross { get; set; }

        [Parameter("Días de la media de volatilidad", DefaultValue = 32, MinValue = 5, MaxValue = 250, Group = "Riesgo")]
        public int VolSpan { get; set; }

        [Parameter("Umbral de rebalanceo (fracción del capital)", DefaultValue = 0.1, MinValue = 0, MaxValue = 1, Group = "Riesgo")]
        public double RebalanceBuffer { get; set; }

        [Parameter("Días de mercado por año", DefaultValue = 252, MinValue = 200, MaxValue = 366, Group = "Riesgo")]
        public int PeriodsPerYear { get; set; }

        [Parameter("Parar si la caída desde máximos supera (%)", DefaultValue = 30, MinValue = 0, MaxValue = 100, Group = "Seguridad")]
        public double MaxDrawdownPercent { get; set; }

        [Parameter("Solo simular (no enviar órdenes)", DefaultValue = true, Group = "Seguridad")]
        public bool DryRun { get; set; }

        [Parameter("Velas diarias mínimas de historia", DefaultValue = 600, MinValue = 300, MaxValue = 5000, Group = "Datos")]
        public int MinHistoryBars { get; set; }

        private readonly List<Symbol> _symbols = new List<Symbol>();
        private readonly Dictionary<string, Bars> _bars = new Dictionary<string, Bars>();
        private readonly Dictionary<string, double> _pendingWeights = new Dictionary<string, double>();
        private DateTime _lastSignalDate = DateTime.MinValue;
        private double _peakEquity;

        protected override void OnStart()
        {
            var names = string.IsNullOrWhiteSpace(SymbolList)
                ? new[] { SymbolName }
                : SymbolList.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).Distinct().ToArray();

            foreach (var name in names)
            {
                var symbol = Symbols.GetSymbol(name);
                if (symbol == null)
                {
                    Print("Símbolo no encontrado en este bróker: {0}. Se detiene el cBot.", name);
                    Stop();
                    return;
                }
                var bars = MarketData.GetBars(TimeFrame.Daily, name);
                while (bars.Count < MinHistoryBars + 1 && bars.LoadMoreHistory() > 0)
                {
                }
                if (bars.Count < MinHistoryBars + 1)
                    Print("Aviso: {0} solo tiene {1} velas diarias; se esperará a tener {2}.", name, bars.Count, MinHistoryBars + 1);
                _symbols.Add(symbol);
                _bars[name] = bars;
            }

            _peakEquity = Account.Equity;
            Print("Cartera: {0}. {1}", string.Join(", ", names), DryRun ? "MODO SIMULACIÓN: no se envían órdenes." : "Operando en real.");
            Timer.Start(TimeSpan.FromMinutes(15));
            Rebalance();
        }

        protected override void OnTimer()
        {
            Rebalance();
        }

        private void Rebalance()
        {
            if (CheckDrawdown())
                return;

            var aligned = AlignClosedBars(out var lastDate);
            if (aligned == null)
                return;

            if (lastDate > _lastSignalDate)
            {
                _lastSignalDate = lastDate;
                var weights = EnsembleMath.TargetWeights(
                    aligned, AllowShort, AssetTargetVol, AssetMaxLeverage, PortfolioTargetVol,
                    MaxGross, VolSpan, PeriodsPerYear);
                _pendingWeights.Clear();
                for (int k = 0; k < _symbols.Count; k++)
                    _pendingWeights[_symbols[k].Name] = weights[k];
                Print("Señal del {0:yyyy-MM-dd} ({1} días comunes): {2}", lastDate, aligned[0].Length,
                    string.Join(", ", _symbols.Select((s, k) => string.Format("{0} {1:P1}", s.Name, weights[k]))));
                ChooseTrades();
            }

            ExecutePending();
        }

        // Decide qué símbolos hay que ajustar según el umbral de rebalanceo.
        private void ChooseTrades()
        {
            double buffer = RebalanceBuffer / _symbols.Count;
            var current = _symbols.ToDictionary(s => s.Name, s => CurrentWeight(s));
            var trade = new HashSet<string>();
            foreach (var s in _symbols)
            {
                double target = _pendingWeights[s.Name];
                if ((target == 0 && current[s.Name] != 0) || Math.Abs(target - current[s.Name]) >= buffer)
                    trade.Add(s.Name);
            }
            // Si los pesos que no se tocan dejan la cartera por encima del
            // límite bruto, se rebalancea todo.
            double gross = _symbols.Sum(s => Math.Abs(trade.Contains(s.Name) ? _pendingWeights[s.Name] : current[s.Name]));
            if (gross > MaxGross + 1e-9)
                trade = new HashSet<string>(_symbols.Select(s => s.Name));

            foreach (var s in _symbols.Where(s => !trade.Contains(s.Name)))
                _pendingWeights.Remove(s.Name);
        }

        private void ExecutePending()
        {
            foreach (var symbol in _symbols)
            {
                if (!_pendingWeights.TryGetValue(symbol.Name, out var weight))
                    continue;
                if (!symbol.MarketHours.IsOpened())
                    continue;
                if (SetPosition(symbol, weight))
                    _pendingWeights.Remove(symbol.Name);
            }
        }

        // Lleva la posición neta del símbolo al peso indicado. Devuelve true si
        // ya está (o si en simulación se ha registrado la orden).
        private bool SetPosition(Symbol symbol, double weight)
        {
            double unitValue = UnitValue(symbol);
            if (unitValue <= 0)
            {
                Print("{0}: no se puede calcular el valor por unidad; se reintentará.", symbol.Name);
                return false;
            }
            double targetUnits = weight * Account.Equity / unitValue;
            double volume = symbol.NormalizeVolumeInUnits(Math.Abs(targetUnits), RoundingMode.ToNearest);
            if (volume < symbol.VolumeInUnitsMin)
                volume = 0;
            volume = Math.Min(volume, symbol.VolumeInUnitsMax);
            var direction = targetUnits >= 0 ? TradeType.Buy : TradeType.Sell;

            var positions = Positions.FindAll(Label, symbol.Name);
            double netUnits = positions.Sum(p => p.TradeType == TradeType.Buy ? p.VolumeInUnits : -p.VolumeInUnits);
            double desiredUnits = direction == TradeType.Buy ? volume : -volume;
            if (Math.Abs(desiredUnits - netUnits) < symbol.VolumeInUnitsStep / 2)
                return true;

            Print("{0}: objetivo {1:P1} del capital -> {2} unidades (ahora {3}).", symbol.Name, weight, desiredUnits, netUnits);
            if (DryRun)
                return true;

            bool ok = true;
            // Cierra lo que va en sentido contrario o sobra; con cuentas de
            // cobertura puede haber varias posiciones.
            foreach (var p in positions)
            {
                bool sameSide = volume > 0 && p.TradeType == direction;
                if (!sameSide)
                    ok &= Check(ClosePosition(p), symbol);
            }
            if (volume == 0)
                return ok;

            var remaining = Positions.FindAll(Label, symbol.Name).Where(p => p.TradeType == direction).ToList();
            double held = remaining.Sum(p => p.VolumeInUnits);
            if (remaining.Count > 1)
            {
                foreach (var p in remaining)
                    ok &= Check(ClosePosition(p), symbol);
                held = 0;
            }
            if (held == 0)
                return ok & Check(ExecuteMarketOrder(direction, symbol.Name, volume, Label), symbol);
            return ok & Check(ModifyPosition(remaining[0], volume), symbol);
        }

        private bool Check(TradeResult result, Symbol symbol)
        {
            if (result.IsSuccessful)
                return true;
            Print("{0}: la orden ha fallado ({1}); se reintentará.", symbol.Name, result.Error);
            return false;
        }

        // Valor en la divisa de la cuenta de 1 unidad del símbolo.
        private static double UnitValue(Symbol symbol)
        {
            double price = (symbol.Bid + symbol.Ask) / 2;
            if (symbol.TickSize <= 0 || double.IsNaN(price) || price <= 0)
                return 0;
            return price * symbol.TickValue / symbol.TickSize;
        }

        private double CurrentWeight(Symbol symbol)
        {
            double unitValue = UnitValue(symbol);
            if (unitValue <= 0 || Account.Equity <= 0)
                return 0;
            double net = Positions.FindAll(Label, symbol.Name)
                .Sum(p => p.TradeType == TradeType.Buy ? p.VolumeInUnits : -p.VolumeInUnits);
            return net * unitValue / Account.Equity;
        }

        private bool CheckDrawdown()
        {
            _peakEquity = Math.Max(_peakEquity, Account.Equity);
            if (MaxDrawdownPercent <= 0 || Account.Equity >= _peakEquity * (1 - MaxDrawdownPercent / 100))
                return false;
            Print("Caída del {0:P1} desde el máximo: se cierran las posiciones y se detiene el cBot.",
                1 - Account.Equity / _peakEquity);
            if (!DryRun)
                foreach (var p in Positions.FindAll(Label))
                    ClosePosition(p);
            Stop();
            return true;
        }

        // Cierres de velas diarias ya terminadas, en las fechas comunes a
        // todos los símbolos. Devuelve null si aún no hay historia suficiente.
        private double[][] AlignClosedBars(out DateTime lastDate)
        {
            lastDate = DateTime.MinValue;
            var series = new List<Dictionary<DateTime, double>>();
            foreach (var symbol in _symbols)
            {
                var bars = _bars[symbol.Name];
                var closes = new Dictionary<DateTime, double>();
                // La última vela aún se está formando: se excluye.
                for (int i = 0; i < bars.Count - 1; i++)
                    closes[bars.OpenTimes[i].Date] = bars.ClosePrices[i];
                series.Add(closes);
            }
            var dates = series[0].Keys.Where(d => series.All(s => s.ContainsKey(d))).OrderBy(d => d).ToList();
            if (dates.Count < MinHistoryBars)
                return null;
            lastDate = dates[dates.Count - 1];
            return series.Select(s => dates.Select(d => s[d]).ToArray()).ToArray();
        }
    }

    // Cálculos de la estrategia, sin dependencias de cTrader. Replican
    // trend_ensemble, volatility_target y portfolio_vol_target de
    // scripts/trend_strategies.py.
    public static class EnsembleMath
    {
        public static readonly int[][] Pairs = { new[] { 8, 32 }, new[] { 16, 64 }, new[] { 32, 128 }, new[] { 64, 256 } };

        public static double[] Ema(double[] values, int window)
        {
            var result = new double[values.Length];
            for (int i = 0; i < result.Length; i++)
                result[i] = double.NaN;
            if (values.Length < window)
                return result;
            double alpha = 2.0 / (window + 1);
            double sum = 0;
            for (int i = 0; i < window; i++)
                sum += values[i];
            result[window - 1] = sum / window;
            for (int i = window; i < values.Length; i++)
                result[i] = alpha * values[i] + (1 - alpha) * result[i - 1];
            return result;
        }

        // Señal del conjunto en la última barra: media de los votos.
        public static double EnsembleSignal(double[] closes, bool allowShort)
        {
            int last = closes.Length - 1;
            double votes = 0;
            foreach (var pair in Pairs)
            {
                double fast = Ema(closes, pair[0])[last];
                double slow = Ema(closes, pair[1])[last];
                if (double.IsNaN(fast) || double.IsNaN(slow))
                    return 0;
                if (fast > slow)
                    votes += 1;
                else if (allowShort && fast < slow)
                    votes -= 1;
            }
            return votes / Pairs.Length;
        }

        // Volatilidad anual en la última barra (media exponencial de los
        // retornos logarítmicos al cuadrado, sembrada con los `span` primeros).
        public static double Volatility(double[] closes, int span, int periodsPerYear)
        {
            if (closes.Length <= span)
                return double.NaN;
            double alpha = 2.0 / (span + 1);
            double variance = 0;
            for (int i = 1; i < closes.Length; i++)
            {
                double r = Math.Log(closes[i] / closes[i - 1]);
                if (i <= span)
                {
                    variance += r * r / span;
                }
                else
                {
                    variance = alpha * r * r + (1 - alpha) * variance;
                }
            }
            return Math.Sqrt(variance * periodsPerYear);
        }

        // Covarianzas exponenciales de los retornos simples en la última barra.
        public static double[,] Covariance(double[][] closes, int span)
        {
            int k = closes.Length, n = closes[0].Length;
            double alpha = 2.0 / (span + 1);
            var cov = new double[k, k];
            for (int i = 1; i < n; i++)
            {
                var r = new double[k];
                for (int a = 0; a < k; a++)
                    r[a] = closes[a][i] / closes[a][i - 1] - 1;
                for (int a = 0; a < k; a++)
                    for (int b = 0; b < k; b++)
                        cov[a, b] = i <= span
                            ? cov[a, b] + r[a] * r[b] / span
                            : alpha * r[a] * r[b] + (1 - alpha) * cov[a, b];
            }
            return cov;
        }

        // Pesos objetivo (fracción del capital, con signo) para la última barra.
        public static double[] TargetWeights(double[][] closes, bool allowShort, double assetTargetVol,
            double assetMaxLeverage, double portfolioTargetVol, double maxGross, int span, int periodsPerYear)
        {
            int k = closes.Length;
            var weights = new double[k];
            for (int a = 0; a < k; a++)
            {
                double signal = EnsembleSignal(closes[a], allowShort);
                double vol = Volatility(closes[a], span, periodsPerYear);
                if (signal == 0 || double.IsNaN(vol))
                    continue;
                double scale = vol > 0 ? assetTargetVol / vol : assetMaxLeverage;
                weights[a] = Math.Max(-assetMaxLeverage, Math.Min(assetMaxLeverage, signal * scale)) / k;
            }

            double gross = weights.Sum(Math.Abs);
            if (gross == 0 || closes[0].Length <= span)
                return new double[k];
            var cov = Covariance(closes, span);
            double variance = 0;
            for (int a = 0; a < k; a++)
                for (int b = 0; b < k; b++)
                    variance += weights[a] * weights[b] * cov[a, b];
            double portfolioVol = Math.Sqrt(Math.Max(variance, 0) * periodsPerYear);
            double factor = portfolioVol > 0 ? portfolioTargetVol / portfolioVol : double.PositiveInfinity;
            factor = Math.Min(factor, maxGross / gross);
            return weights.Select(w => w * factor).ToArray();
        }
    }
}
