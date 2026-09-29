// Uso: dotnet run -- cierres.csv 300,800,1500 pesos.csv
// cierres.csv: cabecera + una columna de cierres por activo (fechas alineadas).
// Escribe, para cada barra pedida, los pesos que calcularía el cBot.
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using cAlgo.Robots;

var rows = File.ReadAllLines(args[0]).Skip(1)
    .Select(l => l.Split(',').Select(x => double.Parse(x, CultureInfo.InvariantCulture)).ToArray())
    .ToArray();
int k = rows[0].Length;
var output = new List<string>();
foreach (var s in args[1].Split(','))
{
    int bar = int.Parse(s);
    var closes = Enumerable.Range(0, k)
        .Select(a => rows.Take(bar + 1).Select(r => r[a]).ToArray())
        .ToArray();
    var weights = EnsembleMath.TargetWeights(closes, false, 0.15, 1.0, 0.10, 1.0, 32, 252);
    output.Add(bar + "," + string.Join(",", weights.Select(w => w.ToString("R", CultureInfo.InvariantCulture))));
}
File.WriteAllLines(args[2], output);
